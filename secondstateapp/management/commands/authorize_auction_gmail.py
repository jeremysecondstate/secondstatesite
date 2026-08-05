from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from secondstateapp.auction_email import GMAIL_SEND_SCOPE, REQUIRED_SENDER


class Command(BaseCommand):
    help = (
        "Authorize the configured Google OAuth desktop client for Gmail send access and print "
        "a refresh token without writing it to disk."
    )

    def handle(self, *args, **options):
        client_id = str(settings.GOOGLE_GMAIL_CLIENT_ID or "").strip()
        client_secret = str(settings.GOOGLE_GMAIL_CLIENT_SECRET or "").strip()
        sender = str(settings.AUCTION_EMAIL_SENDER or "").strip()
        if sender.casefold() != REQUIRED_SENDER:
            raise CommandError(f"AUCTION_EMAIL_SENDER must be {REQUIRED_SENDER}.")
        if not client_id or not client_secret:
            raise CommandError("GOOGLE_GMAIL_CLIENT_ID and GOOGLE_GMAIL_CLIENT_SECRET are required.")

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise CommandError("Install google-auth-oauthlib before running this command.") from exc

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, scopes=[GMAIL_SEND_SCOPE])
        self.stdout.write(
            f"A browser will open. Sign in as {REQUIRED_SENDER} and grant only Gmail send access."
        )
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            access_type="offline",
            prompt="consent",
            include_granted_scopes="false",
            login_hint=REQUIRED_SENDER,
            authorization_prompt_message="Open this URL to authorize the SecondState Gmail sender:\n{url}",
            success_message="Authorization complete. Return to the terminal.",
        )
        refresh_token = str(credentials.refresh_token or "").strip()
        if not refresh_token:
            raise CommandError(
                "Google did not return a refresh token. Revoke the app grant for the sender and run the command again."
            )
        self.stdout.write("\nGOOGLE_GMAIL_REFRESH_TOKEN=")
        self.stdout.write(refresh_token)
        self.stdout.write(
            self.style.WARNING("Copy the token into the secret environment. This command did not write it to a file.")
        )
