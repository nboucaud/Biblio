import hmac
import re

import sqlalchemy as sa

from h.auth import role
from h.models import User
from h.models.auth_client import AuthClient, GrantType
from h.security import Identity


def groupfinder(userid, request):
    """
    Return the list of additional principals for a userid, or None.

    This loads the user and then calls ``principals_for_user``.

    If `userid` identifies a valid user in the system, this function will
    return the list of additional principals for that user. If `userid` is not
    recognised as a valid user in the system, the function will return None.

    :param userid: the userid claimed by the request.
    :type userid: str
    :param request: the request object
    :type request: pyramid.request.Request

    :returns: additional principals for the user (possibly empty) or None
    :rtype: list or None
    """
    user_service = request.find_service(name="user")
    user = user_service.fetch(userid)

    return principals_for_user(user)


def principals_for_identity(identity: Identity):
    if not identity:
        return None

    principals = set()

    if user := identity.user:
        principals.add(role.User)
        if user.admin:
            principals.add(role.Admin)
        if user.staff:
            principals.add(role.Staff)
        for group in user.groups:
            principals.add("group:{group.pubid}".format(group=group))
        principals.add("authority:{authority}".format(authority=user.authority))

    if auth_client := identity.auth_client:
        principals.add(
            "client:{client_id}@{authority}".format(
                client_id=auth_client.id, authority=auth_client.authority
            )
        )
        principals.add(
            "client_authority:{authority}".format(authority=auth_client.authority)
        )
        principals.add(role.AuthClient)

    if identity.user and identity.auth_client:
        principals.add(identity.user.userid)
        principals.add(role.AuthClientUser)

    return list(principals) or None


def principals_for_user(user: User):
    """Return the list of additional principals for a user, or None."""
    return principals_for_identity(Identity(user=user))


def principals_for_auth_client(client: AuthClient):
    """Return the list of additional principals for an auth client."""

    return principals_for_identity(Identity(auth_client=client))


def principals_for_auth_client_user(user: User, client: AuthClient):
    """Return a union of client and user principals for forwarded user."""
    return principals_for_identity(Identity(user=user, auth_client=client))


def default_authority(request):
    """
    Return the value of the h.authority config settings.

    Falls back on returning request.domain if h.authority isn't set.
    """
    return request.registry.settings.get("h.authority", request.domain)


def client_authority(request):
    """
    Return the authority associated with an authenticated auth_client or None.

    Once a request with an auth_client is authenticated, a principal is set
    indicating the auth_client's verified authority

    see :func:`~h.auth.util.principals_for_auth_client` for more details on
    principals applied when auth_clients are authenticated

    :rtype: str or None
    """
    for principal in request.effective_principals:
        match = re.match(r"^client_authority:(.+)$", principal)
        if match and match.group(1):
            return match.group(1)

    return None


def verify_auth_client(client_id, client_secret, db_session):
    """
    Return matching AuthClient or None.

    Attempt to retrieve the :py:class:`h.models.auth_client.AuthClient` record
    indicated by ``client_id`` and ``client_secret`` and perform some validation
    checks on the record.

    Returns ``None`` if retrieval or any checks fail

    :rtype: :py:class:`h.models.auth_client.AuthClient` or ``None``
    """

    # We fetch the client by its ID and then do a constant-time comparison of
    # the secret with that provided in the request.
    #
    # It is important not to include the secret as part of the SQL query
    # because the resulting code may be subject to a timing attack.
    try:  # fetch matching AuthClient record for `client_id`
        client = db_session.query(AuthClient).get(client_id)
    except sa.exc.StatementError:  # query: client_id is malformed
        return None
    if client is None:  # no record returned from query
        return None
    if client.secret is None:  # client is not confidential
        return None
    if client.grant_type != GrantType.client_credentials:  # need these for auth_clients
        return None

    if not hmac.compare_digest(client.secret, client_secret):
        return None

    return client
