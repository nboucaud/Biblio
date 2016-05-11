# -*- coding: utf-8 -*-

import mock
import pytest

from h.test import factories

from h import db
from h.features.models import Feature, FeatureCohort


@pytest.mark.usefixtures('features_override',
                         'features_pending_removal_override')
class TestFeature(object):
    def test_description_returns_hardcoded_description(self):
        feat = Feature(name='notification')

        assert feat.description == 'A test flag for testing with.'

    def test_all_creates_annotations_that_dont_exist(self):
        features = Feature.all()

        assert len(features) == 1
        assert features[0].name == 'notification'

    def test_all_only_returns_current_flags(self):
        """The .all() method should only return named current feature flags."""
        session = db.Session
        new, pending, old = [Feature(name='notification'),
                             Feature(name='abouttoberemoved'),
                             Feature(name='somethingelse')]
        session.add_all([new, pending, old])
        session.flush()

        features = Feature.all()

        assert len(features) == 1
        assert features[0].name == 'notification'

    def test_remove_old_flag_removes_old_flags(self):
        """
        The remove_old_flags function should remove unknown flags.

        New flags and flags pending removal should be left alone, but completely
        unknown flags should be removed.
        """
        session = db.Session
        new, pending, old = [Feature(name='notification'),
                             Feature(name='abouttoberemoved'),
                             Feature(name='somethingelse')]
        session.add_all([new, pending, old])
        session.flush()

        Feature.remove_old_flags()

        remaining = set([f.name for f in session.query(Feature).all()])
        assert remaining == {'abouttoberemoved', 'notification'}

    @pytest.fixture
    def features_override(self, request):
        # Replace the primary FEATURES dictionary for the duration of testing...
        patcher = mock.patch.dict('h.features.models.FEATURES', {
            'notification': "A test flag for testing with."
        }, clear=True)
        patcher.start()
        request.addfinalizer(patcher.stop)

    @pytest.fixture
    def features_pending_removal_override(self, request):
        # And configure 'abouttoberemoved' as a feature pending removal...
        patcher = mock.patch.dict('h.features.models.FEATURES_PENDING_REMOVAL', {
            'abouttoberemoved': "A test flag that's about to be removed."
        }, clear=True)
        patcher.start()
        request.addfinalizer(patcher.stop)


class TestCohort(object):
    def test_init(self):
        name = "My Hypothesis Cohort"

        cohort = FeatureCohort(name=name)
        db.Session.add(cohort)
        db.Session.flush()

        assert cohort.id
        assert cohort.name == name
        assert cohort.created
        assert cohort.updated

    def test_get_by_id_when_id_does_exist(self):
        name = "My Hypothesis Cohort"

        cohort = FeatureCohort(name=name)
        db.Session.add(cohort)
        db.Session.flush()

        assert FeatureCohort.query.get(cohort.id) == cohort

    def test_get_by_id_when_id_does_not_exist(self):
        name = "My Hypothesis Cohort"

        cohort = FeatureCohort(name=name)
        db.Session.add(cohort)
        db.Session.flush()

        assert FeatureCohort.query.get(23) is None
