"""The personal join link STYD sends to an Odoo user who is not linked yet.

STYD answers such a question with a refusal (``join_required``) whose message
holds the link on a line of its own, and may add a top-level ``action`` (a
button) that this version does not use. The module needs no code for it: these
tests pin that the link comes through whole, as plain text, and that ``action``
is dropped."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.styd_odoo_bridge.models import bridge_discuss_text as text_mod

# The token's shape on STYD's side: dj1.<workspace>.<pairing>.<Odoo user>.<expiry>.<nonce 32 hex>.<HMAC 64 hex>
TOKEN = ("dj1.42.bp_AbCdEfGhIjKlMnOpQrStUv.7.1795000000."
         "0123456789abcdef0123456789abcdef."
         "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
LINK = "https://app.speaktoyourdatabase.com/join/odoo?t=" + TOKEN
SHOWN = "app[.]speaktoyourdatabase[.]com/join/odoo?t=" + TOKEN

MESSAGES = {
    "en": "To get answers here, join your team on Speak To Your Database:\n%s\n"
          "This link is for you only. It works once, for 30 minutes.",
    "fr": "Pour obtenir des réponses ici, rejoignez votre équipe sur Speak To Your Database :\n%s\n"
          "Ce lien vous est personnel. Il ne fonctionne qu’une fois, pendant 30 minutes.",
    "ar": "للحصول على إجابات هنا، انضم إلى فريقك على Speak To Your Database:\n%s\n"
          "هذا الرابط لك وحدك. يعمل مرة واحدة فقط، لمدة 30 دقيقة.",
}


def join_answer(message, lang="en"):
    return {
        "question_id": "dq_" + "a" * 22,
        "status": "refused",
        "lang": lang,
        "refusal": {"code": "join_required", "message": message},
        "action": {"type": "open_url", "label": "Join your team", "url": LINK},
    }


@tagged("post_install", "-at_install")
class TestJoinLink(TransactionCase):
    def test_01_link_shown_whole_as_plain_text(self):
        for lang, template in MESSAGES.items():
            answer = text_mod.validate_answer(join_answer(template % LINK, lang=lang))
            html = str(text_mod.render_answer(answer, "en_US"))
            self.assertIn(SHOWN, html, lang)
            self.assertNotIn(text_mod.HIDDEN, html, lang)
            self.assertNotIn("https://", html, lang)
            self.assertNotIn("<a ", html, lang)
            # The link stays on a line of its own.
            self.assertIn("<br/>%s<br/>" % SHOWN, html, lang)

    def test_02_action_is_not_used(self):
        answer = text_mod.validate_answer(join_answer(MESSAGES["en"] % LINK))
        self.assertNotIn("action", answer)
        self.assertEqual(answer["refusal"]["code"], "join_required")
        html = str(text_mod.render_answer(answer, "en_US"))
        self.assertNotIn("Join your team", html)
        self.assertNotIn("button", html)

    def test_03_other_join_refusals_are_plain_lines(self):
        for code, message in (
                ("ask_in_direct_message", "Please ask me in a direct message: I will send you a link to join "
                                          "your team on Speak To Your Database."),
                ("join_limit", "We sent you a link to join your team a short while ago: please use the latest one. "
                               "You can ask for a new link in an hour.")):
            answer = text_mod.validate_answer({
                "question_id": "dq_" + "b" * 22, "status": "refused", "lang": "en",
                "refusal": {"code": code, "message": message}})
            self.assertEqual(answer["refusal"]["code"], code)
            self.assertEqual(str(text_mod.render_answer(answer, "en_US")), "<p>%s</p>" % message)

    def test_04_a_real_secret_next_to_the_link_is_still_hidden(self):
        secret = "S" * 43
        answer = text_mod.validate_answer(join_answer((MESSAGES["en"] % LINK) + " " + secret))
        html = str(text_mod.render_answer(answer, "en_US", secrets=(secret,)))
        self.assertIn(SHOWN, html)
        self.assertNotIn(secret, html)
        self.assertIn(text_mod.HIDDEN, html)
