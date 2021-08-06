from h.security.permissions import Permission
from h.traversal import AnnotationContext


class AnnotationHiddenFormatter:
    """
    Formatter for dealing with annotations that a moderator has hidden.

    Any user who has permission to moderate a group will always be able to see
    whether annotations in a group have been hidden, and will be able to see
    the content of those annotations. In the unlikely event that these
    annotations are their own, they'll still be able to see them.

    Moderators aside, users are never shown that their own annotations have
    been hidden. They are always given a `False` value for the `hidden` flag.

    For any other users, if an annotation has been hidden it is presented with
    the `hidden` flag set to `True`, and the annotation's content is redacted.
    """

    def __init__(self, moderation_svc, has_permission, user):
        self._moderation_svc = moderation_svc
        self._has_permission = has_permission
        self._user = user

        # Local cache of hidden flags. We don't need to care about detached
        # instances because we only store the annotation id and a boolean flag.
        self._cache = {}

    def preload(self, annotation_ids):
        hidden_ids = self._moderation_svc.all_hidden(annotation_ids)

        hidden = {
            annotation_id: (annotation_id in hidden_ids)
            for annotation_id in annotation_ids
        }
        self._cache.update(hidden)
        return hidden

    def format(self, annotation):
        if self._current_user_is_moderator(annotation):
            return {"hidden": self._is_hidden(annotation)}

        if self._current_user_is_author(annotation):
            return {"hidden": False}

        if self._is_hidden(annotation):
            return {"hidden": True, "text": "", "tags": []}

        return {"hidden": False}

    def _current_user_is_moderator(self, annotation):
        return self._has_permission(
            Permission.Annotation.MODERATE, context=AnnotationContext(annotation)
        )

    def _current_user_is_author(self, annotation):
        return self._user and self._user.userid == annotation.userid

    def _is_hidden(self, annotation):
        id_ = annotation.id

        if id_ in self._cache:
            return self._cache[id_]

        hidden = self._moderation_svc.hidden(annotation)
        self._cache[id_] = hidden
        return self._cache[id_]
