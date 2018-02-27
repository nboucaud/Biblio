# -*- coding: utf-8 -*-

from __future__ import unicode_literals


class GroupLinksService(object):

    """
    A service for providing appropriate links for a given group object
    """

    def __init__(self, request_authority, route_url):
        """
        Create a group_links service.

        :param request_authority: The request's "default" authority
        """
        self._authority = request_authority
        self._route_url = route_url

    def get_all(self, group):
        """Return all links"""
        links = {}
        if group.authority == self._authority:
            # Only groups for the default authority should have an activity page
            # link. Note that the default authority may differ from the
            # user's authority.
            links['group'] = self._route_url('group_read',
                                             pubid=group.pubid,
                                             slug=group.slug)
        return links


def group_links_factory(context, request):
    """Return a GroupLinksService instance for the passed context and request."""
    return GroupLinksService(request_authority=request.authority,
                             route_url=request.route_url)
