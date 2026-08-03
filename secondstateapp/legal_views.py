from django.conf import settings
from django.shortcuts import render


def sms_program(request):
    return render(
        request,
        "legal/sms_program.html",
        {
            "sms_number": settings.TWILIO_FROM_NUMBER.strip(),
        },
    )


def privacy_policy(request):
    return render(request, "legal/privacy.html")


def sms_terms(request):
    return render(request, "legal/sms_terms.html")
