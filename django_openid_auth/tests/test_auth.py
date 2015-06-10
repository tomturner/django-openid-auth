# django-openid-auth -  OpenID integration for django.contrib.auth
#
# Copyright (C) 2010-2013 Canonical Ltd.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import (
    Group,
    Permission,
    User,
)
from django.test import TestCase

from django_openid_auth.auth import OpenIDBackend
from django_openid_auth.models import UserOpenID
from django_openid_auth.teams import ns_uri as TEAMS_NS
from django_openid_auth.tests.helpers import override_session_serializer
from openid.consumer.consumer import SuccessResponse
from openid.consumer.discover import OpenIDServiceEndpoint
from openid.message import Message, OPENID2_NS


SREG_NS = "http://openid.net/sreg/1.0"
AX_NS = "http://openid.net/srv/ax/1.0"


@override_session_serializer
class OpenIDBackendTests(TestCase):

    def setUp(self):
        super(OpenIDBackendTests, self).setUp()
        self.backend = OpenIDBackend()
        self.old_openid_use_email_for_username = getattr(settings,
            'OPENID_USE_EMAIL_FOR_USERNAME', False)
        self.old_openid_launchpad_teams_required = getattr(settings,
            'OPENID_LAUNCHPAD_TEAMS_REQUIRED', [])
        self.old_openid_launchpad_teams_mapping_auto = getattr(settings,
            'OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO', False)
        self.old_openid_email_whitelist_regexp_list = getattr(settings,
            'OPENID_EMAIL_WHITELIST_REGEXP_LIST', [])

    def tearDown(self):
        settings.OPENID_USE_EMAIL_FOR_USERNAME = \
            self.old_openid_use_email_for_username
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = (
            self.old_openid_launchpad_teams_required)
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = (
            self.old_openid_launchpad_teams_mapping_auto)
        settings.OPENID_EMAIL_WHITELIST_REGEXP_LIST = (
            self.old_openid_email_whitelist_regexp_list)

    def test_extract_user_details_sreg(self):
        expected = {
            'nickname': 'someuser',
            'first_name': 'Some',
            'last_name': 'User',
            'email': 'foo@example.com',
            'account_verified': False,
        }
        data = {
            'nickname': expected['nickname'],
            'fullname': "%s %s" % (expected['first_name'],
                                   expected['last_name']),
            'email': expected['email'],
        }
        response = self.make_response_sreg(**data)

        details = self.backend._extract_user_details(response)
        self.assertEqual(details, expected)

    def make_fake_openid_endpoint(self, claimed_id=None):
        endpoint = OpenIDServiceEndpoint()
        endpoint.claimed_id = claimed_id
        return endpoint

    def make_openid_response(self, sreg_args=None, teams_args=None):
        endpoint = self.make_fake_openid_endpoint(claimed_id='some-id')
        message = Message(OPENID2_NS)
        if sreg_args is not None:
            for key, value in sreg_args.items():
                message.setArg(SREG_NS, key, value)
        if teams_args is not None:
            for key, value in teams_args.items():
                message.setArg(TEAMS_NS, key, value)
        response = SuccessResponse(
            endpoint, message, signed_fields=message.toPostArgs().keys())
        return response

    def make_response_sreg(self, **kwargs):
        response = self.make_openid_response(sreg_args=kwargs)
        return response

    def make_response_ax(self, schema="http://axschema.org/",
            fullname="Some User", nickname="someuser", email="foo@example.com",
            first=None, last=None, verified=False):
        endpoint = OpenIDServiceEndpoint()
        message = Message(OPENID2_NS)
        attributes = [
            ("nickname", schema + "namePerson/friendly", nickname),
            ("fullname", schema + "namePerson", fullname),
            ("email", schema + "contact/email", email),
            ("account_verified",
             "http://ns.login.ubuntu.com/2013/validation/account",
             "token_via_email" if verified else "no")
            ]
        if first:
            attributes.append(
                ("first", "http://axschema.org/namePerson/first", first))
        if last:
            attributes.append(
                ("last", "http://axschema.org/namePerson/last", last))

        message.setArg(AX_NS, "mode", "fetch_response")
        for (alias, uri, value) in attributes:
            message.setArg(AX_NS, "type.%s" % alias, uri)
            message.setArg(AX_NS, "value.%s" % alias, value)
        return SuccessResponse(
            endpoint, message, signed_fields=message.toPostArgs().keys())

    def test_extract_user_details_ax(self):
        response = self.make_response_ax(fullname="Some User",
            nickname="someuser", email="foo@example.com")

        data = self.backend._extract_user_details(response)

        self.assertEqual(data, {"nickname": "someuser",
                                "first_name": "Some",
                                "last_name": "User",
                                "email": "foo@example.com",
                                "account_verified": False})

    def test_extract_user_details_ax_split_name(self):
        # Include fullname too to show that the split data takes
        # precedence.
        response = self.make_response_ax(
            fullname="Bad Data", first="Some", last="User")

        data = self.backend._extract_user_details(response)

        self.assertEqual(data, {"nickname": "someuser",
                                "first_name": "Some",
                                "last_name": "User",
                                "email": "foo@example.com",
                                "account_verified": False})

    def test_extract_user_details_ax_broken_myopenid(self):
        response = self.make_response_ax(
            schema="http://schema.openid.net/", fullname="Some User",
            nickname="someuser", email="foo@example.com")

        data = self.backend._extract_user_details(response)

        self.assertEqual(data, {"nickname": "someuser",
                                "first_name": "Some",
                                "last_name": "User",
                                "email": "foo@example.com",
                                "account_verified": False})

    def test_update_user_details_long_names(self):
        response = self.make_response_ax()
        user = User.objects.create_user('someuser', 'someuser@example.com',
            password=None)
        user_openid, created = UserOpenID.objects.get_or_create(
            user=user,
            claimed_id='http://example.com/existing_identity',
            display_id='http://example.com/existing_identity')
        data = dict(first_name=u"Some56789012345678901234567890123",
            last_name=u"User56789012345678901234567890123",
            email=u"someotheruser@example.com", account_verified=False)

        self.backend.update_user_details(user, data, response)

        self.assertEqual("Some56789012345678901234567890",  user.first_name)
        self.assertEqual("User56789012345678901234567890",  user.last_name)

    def make_user(self, username='someuser', email='someuser@example.com',
                password=None):
        user = User.objects.create_user(username, email, password=password)
        return user

    def make_user_openid(self, user=None,
                         claimed_id='http://example.com/existing_identity',
                         display_id='http://example.com/existing_identity'):
        if user is None:
            user = self.make_user()
        user_openid, created = UserOpenID.objects.get_or_create(
            user=user, claimed_id=claimed_id, display_id=display_id)
        return user_openid

    def _test_account_verified(self, user, initially_verified, expected):
        # set user's verification status
        permission = Permission.objects.get(codename='account_verified')
        if initially_verified:
            user.user_permissions.add(permission)
        else:
            user.user_permissions.remove(permission)

        if hasattr(user, '_perm_cache'):
            del user._perm_cache

        # get a response including verification status
        response = self.make_response_ax()
        data = dict(first_name=u"Some56789012345678901234567890123",
                    last_name=u"User56789012345678901234567890123",
                    email=u"someotheruser@example.com",
                    account_verified=expected)
        self.backend.update_user_details(user, data, response)

        # refresh object from the database
        user = get_user_model().objects.get(pk=user.pk)
        # check the verification status
        user_permission = user.has_perm('django_openid_auth.account_verified')
        self.assertEqual(user_permission, expected)

    def test_update_user_perms_unverified(self):
        user_openid = self.make_user_openid()

        for initially_verified in (False, True):
            self._test_account_verified(
                user_openid.user, initially_verified, expected=False)

    def test_update_user_perms_verified(self):
        user_openid = self.make_user_openid()

        for initially_verified in (False, True):
            self._test_account_verified(
                user_openid.user, initially_verified, expected=True)

    def test_extract_user_details_name_with_trailing_space(self):
        response = self.make_response_ax(fullname="SomeUser ")

        data = self.backend._extract_user_details(response)

        self.assertEqual("", data['first_name'])
        self.assertEqual("SomeUser", data['last_name'])

    def test_extract_user_details_name_with_thin_space(self):
        response = self.make_response_ax(fullname=u"Some\u2009User")

        data = self.backend._extract_user_details(response)

        self.assertEqual("Some", data['first_name'])
        self.assertEqual("User", data['last_name'])

    def test_preferred_username_email_munging(self):
        settings.OPENID_USE_EMAIL_FOR_USERNAME = True
        for nick, email, expected in [
            ('nickcomesfirst', 'foo@example.com', 'nickcomesfirst'),
            ('', 'foo@example.com', 'fooexamplecom'),
            ('noemail', '', 'noemail'),
            ('', '@%.-', 'openiduser'),
            ('', '', 'openiduser'),
            (None, None, 'openiduser')]:
            self.assertEqual(expected,
                self.backend._get_preferred_username(nick, email))

    def test_preferred_username_no_email_munging(self):
        for nick, email, expected in [
            ('nickcomesfirst', 'foo@example.com', 'nickcomesfirst'),
            ('', 'foo@example.com', 'openiduser'),
            ('noemail', '', 'noemail'),
            ('', '@%.-', 'openiduser'),
            ('', '', 'openiduser'),
            (None, None, 'openiduser')]:
            self.assertEqual(expected,
                self.backend._get_preferred_username(nick, email))

    def test_authenticate_when_not_member_of_teams_required(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team']
        Group.objects.create(name='team')

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser'),
            teams_args=dict(is_member='foo'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNone(user)

    def test_authenticate_when_no_group_mapping_to_required_team(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team']
        assert Group.objects.filter(name='team').count() == 0

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser'),
            teams_args=dict(is_member='foo'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNone(user)

    def test_authenticate_when_member_of_teams_required(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team']
        Group.objects.create(name='team')

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser'),
            teams_args=dict(is_member='foo,team'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNotNone(user)

    def test_authenticate_when_no_teams_required(self):
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = []

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser'),
            teams_args=dict(is_member='team'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNotNone(user)

    def test_authenticate_when_member_of_at_least_one_team(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team1', 'team2']
        Group.objects.create(name='team1')

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser'),
            teams_args=dict(is_member='foo,team1'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNotNone(user)

    def test_authenticate_when_not_in_required_team_but_email_whitelisted(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team']
        settings.OPENID_EMAIL_WHITELIST_REGEXP_LIST = [
            'foo(\+[^@]*)?@foo.com',
        ]
        assert Group.objects.filter(name='team').count() == 0

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser', email='foo@foo.com'),
            teams_args=dict(is_member='foo'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNotNone(user)

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser', email='foo+bar@foo.com'),
            teams_args=dict(is_member='foo'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNotNone(user)

    def test_authenticate_whitelisted_email_multiple_patterns(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team']
        settings.OPENID_EMAIL_WHITELIST_REGEXP_LIST = [
            'foo@foo.com', 'bar@foo.com',
        ]
        assert Group.objects.filter(name='team').count() == 0

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser', email='bar@foo.com'),
            teams_args=dict(is_member='foo'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNotNone(user)

    def test_authenticate_whitelisted_email_not_match(self):
        settings.OPENID_LAUNCHPAD_TEAMS_MAPPING_AUTO = True
        settings.OPENID_LAUNCHPAD_TEAMS_REQUIRED = ['team']
        settings.OPENID_EMAIL_WHITELIST_REGEXP_LIST = [
            'foo@foo.com',
        ]
        assert Group.objects.filter(name='team').count() == 0

        response = self.make_openid_response(
            sreg_args=dict(nickname='someuser', email='bar@foo.com'),
            teams_args=dict(is_member='foo'))
        user = self.backend.authenticate(openid_response=response)

        self.assertIsNone(user)


def suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
