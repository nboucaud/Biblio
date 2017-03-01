# -*- coding: utf-8 -*-

import datetime
import re

import sqlalchemy as sa
from sqlalchemy.ext.hybrid import Comparator, hybrid_property

from h._compat import text_type
from h.db import Base
from h.security import password_context
from h.util.user import split_user

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 30
USERNAME_PATTERN = '(?i)^[A-Z0-9._]+$'
EMAIL_MAX_LENGTH = 100
PASSWORD_MIN_LENGTH = 2


class UserIDComparator(Comparator):
    """
    Custom comparator for the User.userid property.

    This is a comparator conforming to the
    :py:class:`sqlalchemy.orm.interfaces.PropComparator` interface, which
    makes it possible to find users by userid without doing ugly SQL
    concatenation that prevents the use of indices.
    """
    def __init__(self, username, authority):
        self.username = username
        self.authority = authority

    def __eq__(self, other):
        try:
            val = split_user(other)
        except ValueError:
            # The value being compared isn't a valid userid
            return False
        return sa.and_(val['username'] == self.username,
                       val['domain'] == self.authority)


class UIDComparator(Comparator):
    """
    Custom comparator for the User.username property.

    This ensures that lookups by username are actually always done against the
    :py:attr:`~h.models.user.User.uid` property. This ensures that username
    normalisation is consistently applied when retrieving users by username
    throughout the application.
    """
    def __eq__(self, other):
        return self.__clause_element__() == _username_to_uid(other)


class UserFactory(object):
    """Root resource for routes that look up User objects by traversal."""

    def __init__(self, request):
        self.request = request

    def __getitem__(self, username):
        user = self.request.find_service(name='user').fetch(
            username, self.request.auth_domain)

        if not user:
            raise KeyError()

        return user


class User(Base):
    __tablename__ = 'user'
    __table_args__ = (
        sa.UniqueConstraint('email', 'authority'),
        sa.UniqueConstraint('uid', 'authority'),
        sa.UniqueConstraint('username', 'authority'),
    )

    id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)

    #: Normalised user identifier
    uid = sa.Column(sa.UnicodeText(), nullable=False)
    #: Username as chosen by the user on registration
    _username = sa.Column('username', sa.UnicodeText(), nullable=False)

    #: The "authority" for this user. This represents the "namespace" in which
    #: this user lives. By default, all users are created in the namespace
    #: corresponding to `request.domain`, but this can be overridden with the
    #: `AUTH_DOMAIN` environment variable.
    authority = sa.Column('authority',
                          sa.UnicodeText(),
                          index=True,
                          nullable=False)

    #: The display name which will be used when rendering an annotation.
    display_name = sa.Column(sa.UnicodeText())

    #: A short user description/bio
    description = sa.Column(sa.UnicodeText())

    #: A free-form column to allow the user to say where they are
    location = sa.Column(sa.UnicodeText())

    #: The user's URI/link on the web
    uri = sa.Column(sa.UnicodeText())

    #: The user's ORCID ID
    orcid = sa.Column(sa.UnicodeText())

    #: Is this user an admin member?
    admin = sa.Column(sa.Boolean,
                      default=False,
                      nullable=False,
                      server_default=sa.sql.expression.false())

    #: Is this user a staff member?
    staff = sa.Column(sa.Boolean,
                      nullable=False,
                      default=False,
                      server_default=sa.sql.expression.false())

    #: Is this user flagged as "Not (Suitable) In Public Site Areas" (AKA
    #: NIPSA). This flag is used to shadow-ban a user so their annotations
    #: don't appear to anyone but themselves.
    nipsa = sa.Column(sa.Boolean,
                      nullable=False,
                      default=False,
                      server_default=sa.sql.expression.false())

    sidebar_tutorial_dismissed = sa.Column(sa.Boolean,
                                           default=False,
                                           server_default=(
                                                sa.sql.expression.false()))

    @hybrid_property
    def username(self):
        return self._username

    @username.setter
    def username(self, value):
        self._username = value
        self.uid = _username_to_uid(value)

    @username.comparator
    def username(cls):
        # Whenever a query filters by username, filter by uid instead behind
        # the scenes. This ensures, for example, that login by case- or
        # dot-variant of a username works as expected.
        return UIDComparator(cls.uid)

    @hybrid_property
    def userid(self):
        return u'acct:{username}@{authority}'.format(username=self.username,
                                                     authority=self.authority)

    @userid.comparator
    def userid(cls):
        # Rather than using the default generated by hybrid_property, which
        # would generate SQL like the following:
        #
        #     ... WHERE 'acct:' || username || '@' || authority = ...
        #
        # we use a custom comparator so that we can take advantage of indices
        # on the username and authority columns.
        return UserIDComparator(cls.username, cls.authority)

    email = sa.Column(sa.UnicodeText(), nullable=False)

    last_login_date = sa.Column(sa.TIMESTAMP(timezone=False),
                                default=datetime.datetime.utcnow,
                                server_default=sa.func.now(),
                                nullable=False)
    registered_date = sa.Column(sa.TIMESTAMP(timezone=False),
                                default=datetime.datetime.utcnow,
                                server_default=sa.func.now(),
                                nullable=False)

    # Activation foreign key
    activation_id = sa.Column(sa.Integer, sa.ForeignKey('activation.id'))
    activation = sa.orm.relationship('Activation', backref='user')

    @property
    def is_activated(self):
        if self.activation_id is None:
            return True

        return False

    def activate(self):
        """Activate the user by deleting any activation they have."""
        session = sa.orm.object_session(self)
        session.delete(self.activation)

    #: Hashed password
    _password = sa.Column('password', sa.UnicodeText(), nullable=True)
    #: Last password update
    password_updated = sa.Column(sa.DateTime(), nullable=True)

    #: Password salt
    #:
    #: N.B. This field is DEPRECATED. The password context we use already
    #: manages the generation of a random salt when hashing a password and we
    #: don't need a separate salt column. This remains for "legacy" passwords
    #: which were, sadly, double-salted. As users log in, we are slowly
    #: upgrading their passwords and setting this column to None.
    salt = sa.Column(sa.UnicodeText(), nullable=True)

    @hybrid_property
    def password(self):
        return self._password

    @password.setter
    def password(self, secret):
        if len(secret) < PASSWORD_MIN_LENGTH:
            raise ValueError('password must be more than {min} characters '
                             'long'.format(min=PASSWORD_MIN_LENGTH))
        # Remove any existing explicit salt (the password context salts the
        # password automatically).
        self.salt = None
        self._password = text_type(password_context.encrypt(secret))
        self.password_updated = datetime.datetime.utcnow()

    def check_password(self, secret):
        """Check the passed password for this user."""
        if not self.password:
            return False

        # Old-style separate salt.
        #
        # TODO: remove this deprecated code path when a suitable proportion of
        # users have updated their password by logging-in. (Check how many
        # users still have a non-null salt in the database.)
        if self.salt is not None:
            verified = password_context.verify(secret + self.salt,
                                               self.password)

            # If the password is correct, take this opportunity to upgrade the
            # password and remove the salt.
            if verified:
                self.password = secret

            return verified

        verified, new_hash = password_context.verify_and_update(secret,
                                                                self.password)
        if not verified:
            return False

        if new_hash is not None:
            self._password = text_type(new_hash)

        return verified

    @sa.orm.validates('email')
    def validate_email(self, key, email):
        if len(email) > EMAIL_MAX_LENGTH:
            raise ValueError('email must be less than {max} characters '
                             'long'.format(max=EMAIL_MAX_LENGTH))
        return email

    @sa.orm.validates('_username')
    def validate_username(self, key, username):
        if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
            raise ValueError('username must be between {min} and {max} '
                             'characters long'.format(
                                 min=USERNAME_MIN_LENGTH,
                                 max=USERNAME_MAX_LENGTH))

        if not re.match(USERNAME_PATTERN, username):
            raise ValueError('username must have only letters, numbers, '
                             'periods, and underscores.')

        return username

    @classmethod
    def get_by_email(cls, session, email, authority):
        """Fetch a user by email address."""
        return session.query(cls).filter(
            sa.func.lower(cls.email) == email.lower(),
            cls.authority == authority,
        ).first()

    @classmethod
    def get_by_activation(cls, session, activation):
        """Fetch a user by activation instance."""
        user = session.query(cls).filter(
            cls.activation_id == activation.id
        ).first()

        return user

    @classmethod
    def get_by_username(cls, session, username, authority):
        """Fetch a user by username."""
        uid = _username_to_uid(username)
        return session.query(cls).filter(
            cls.uid == uid,
            cls.authority == authority,
        ).first()

    def __repr__(self):
        return '<User: %s>' % self.username


def _username_to_uid(username):
    # We normalize usernames by dots and case in order to discourage attempts
    # at impersonation.
    return username.replace('.', '').lower()
