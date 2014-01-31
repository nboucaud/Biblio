
import traceback

from pyramid_mailer.interfaces import IMailer
from pyramid_mailer.message import Message
from pyramid_mailer.testing import DummyMailer

from pyramid.events import subscriber
from h import events

import logging
log = logging.getLogger(__name__)


class AnnotationDummyMailer(DummyMailer):
    def __init__(self):
        super(AnnotationDummyMailer, self).__init__()

    def send_annotation(self, annotation, recipients):
        message = Message(subject="Re",
                          sender="admin@hypothes.is",
                          recipients=recipients,
                          body=annotation['text'])
        self.send(message)
        log.info('sent: %s' % message.to_message().as_string())

@subscriber(events.AnnotationEvent)
def send_notifications(event):
    log.info('send_notifications')
    try:
        action = event.action
        if action != 'create':
            return

        request = event.request
        registry = request.registry
        annotation = event.annotation

        mailer = registry.queryUtility(IMailer)
        log.info('------- Mailer -------')
        log.info(mailer)
        mailer.send_annotation(annotation, ['test@test'])

    except:
        log.info(traceback.format_exc())
        log.info('Unexpected error occurred in send_notifications(): ' + str(event))


def includeme(config):
    config.scan(__name__)
    mailer = AnnotationDummyMailer()
    config.registry.registerUtility(mailer, IMailer)
