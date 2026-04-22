from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

from .models import UserProfile


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    display_name = forms.CharField(max_length=120, required=False)
    favorite_artists = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Add a few names separated by commas.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "display_name", "favorite_artists", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]

        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.display_name = self.cleaned_data.get("display_name", "")
            profile.favorite_artists = self.cleaned_data.get("favorite_artists", "")
            profile.save()

        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["display_name", "bio", "favorite_artists", "avatar"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
            "favorite_artists": forms.Textarea(attrs={"rows": 4}),
        }
