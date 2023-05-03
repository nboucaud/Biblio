"""
Annotation storage API.

This module provides the core API with access to basic persistence functions
for storing and retrieving annotations. Data passed to these functions is
assumed to be validated.
"""
# FIXME: This module was originally written to be a single point of
#        indirection through which the storage backend could be swapped out on
#        the fly. This helped us to migrate from Elasticsearch-based
#        persistence to PostgreSQL persistence.
#
#        The purpose of this module is now primarily to serve as a place to
#        wrap up the business logic of creating and retrieving annotations. As
#        such, it probably makes more sense for this to be split up into a
#        couple of different services at some point.

from datetime import datetime

from pyramid import i18n

from h import models, schemas
from h.models.document import update_document_metadata
from h.util.group_scope import url_in_scope
from h.util.uri import normalize as normalize_uri

_ = i18n.TranslationStringFactory(__package__)


def update_annotation(
    request,
    id_,
    data,
    update_timestamp=True,
    reindex_tag="storage.update_annotation",
):  # pylint: disable=too-many-arguments
    """
    Update an existing annotation and its associated document metadata.

    :param request: the request object
    :param id_: the ID of the annotation to be updated, this is assumed to be a
        validated ID of an annotation that does already exists in the database
    :param data: the validated data with which to update the annotation
    :param update_timestamp: Whether to update the last-edited timestamp of the
        annotation.
    :param reindex_tag: Tag used by the reindexing job to identify the source of
        the reindexing request.
    :returns: the updated annotation
    :rtype: h.models.Annotation
    """
    annotation = request.db.query(models.Annotation).get(id_)
    annotation.extra.update(data.pop("extra", {}))

    if update_timestamp:
        annotation.updated = datetime.utcnow()

    uri_changed = data.get("target_uri", annotation.target_uri) != annotation.target_uri

    # Pop the document so we don't set it directly
    document = data.pop("document", {})
    for key, value in data.items():
        setattr(annotation, key, value)

    if target_uri := data.get("target_uri", None):
        _validate_group_scope(annotation.group, target_uri)

    # Expire the group relationship so we get the most up to date value instead
    # of the one one which was present when we loaded the model
    # https://docs.sqlalchemy.org/en/13/faq/sessions.html#i-set-the-foo-id-attribute-on-my-instance-to-7-but-the-foo-attribute-is-still-none-shouldn-t-it-have-loaded-foo-with-id-7
    request.db.expire(annotation, ["group"])
    if annotation.group is None:
        raise schemas.ValidationError(
            "group: " + _("Invalid group specified for annotation")
        )

    if document or uri_changed:
        annotation.document = update_document_metadata(
            request.db,
            annotation.target_uri,
            document.get("document_meta_dicts", {}),
            document.get("document_uri_dicts", {}),
            updated=annotation.updated,
        )

    # The search index service by default does not reindex if the existing ES
    # entry's timestamp matches the DB timestamp. If we're not changing this
    # timestamp, we need to force reindexing.
    force_reindex = not update_timestamp

    request.find_service(  # pylint: disable=protected-access
        name="search_index"
    )._queue.add_by_id(
        annotation.id, tag=reindex_tag, schedule_in=60, force=force_reindex
    )

    return annotation


def expand_uri(session, uri, normalized=False):
    """
    Return all URIs which refer to the same underlying document as `uri`.

    This function determines whether we already have "document" records for the
    passed URI, and if so returns the set of all URIs which we currently
    believe refer to the same document.

    :param session: Database session
    :param uri: URI associated with the document
    :param normalized: Return normalized URIs instead of the raw value

    :returns: a list of equivalent URIs
    """

    normalized_uri = normalize_uri(uri)

    document_id = (
        session.query(models.DocumentURI.document_id)
        .filter(models.DocumentURI.uri_normalized == normalized_uri)
        .limit(1)
        .scalar_subquery()
    )

    type_uris = list(
        session.query(
            # Using the specific fields we want prevents object creation
            # which significantly speeds this method up (knocks ~40% off)
            models.DocumentURI.type,
            models.DocumentURI.uri,
            models.DocumentURI.uri_normalized,
        ).filter(models.DocumentURI.document_id == document_id)
    )

    if not type_uris:
        return [normalized_uri if normalized else uri]

    # We check if the match was a "canonical" link. If so, all annotations
    # created on that page are guaranteed to have that as their target.source
    # field, so we don't need to expand to other URIs and risk false positives.
    for doc_type, plain_uri, _ in type_uris:
        if doc_type == "rel-canonical" and plain_uri == uri:
            return [normalized_uri if normalized else uri]

    if normalized:
        return [uri_normalized for _, _, uri_normalized in type_uris]

    return [plain_uri for _, plain_uri, _ in type_uris]


def _validate_group_scope(group, target_uri):
    # If no scopes are present, or if the group is configured to allow
    # annotations outside of its scope, there's nothing to do here
    if not group.scopes or not group.enforce_scope:
        return
    # The target URI must match at least one
    # of a group's defined scopes, if the group has any
    group_scopes = [scope.scope for scope in group.scopes]
    if not url_in_scope(target_uri, group_scopes):
        raise schemas.ValidationError(
            "group scope: "
            + _("Annotations for this target URI are not allowed in this group")
        )
