from __future__ import annotations

from django import forms

from .models import Project

DEFAULT_BASE_PROMPT = (
    "You are screening articles for a systematic review. For each article you will "
    "receive the title and the abstract. Decide whether it should be included in the "
    "review according to the eligibility criteria listed below.\n\n"
    "Output format (strict, no exceptions):\n"
    "- One yes/no token per line, lowercase, with no punctuation and no prose.\n"
    "- Line 1: the overall inclusion decision (yes = include, no = exclude).\n"
    "- Following lines: one yes/no per eligibility criterion, in order.\n"
    "Do not produce any other output. Do not justify your answers."
)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            "name", "description", "base_prompt", "criteria",
            "prompt_structure", "provider", "model",
            "temperature", "max_tokens", "no_think",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "base_prompt": forms.Textarea(attrs={"rows": 8}),
            "criteria": forms.Textarea(attrs={"rows": 8, "placeholder": "Um criterio por linha (I/E)."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get("base_prompt"):
            self.fields["base_prompt"].initial = DEFAULT_BASE_PROMPT


class RunForm(forms.Form):
    provider = forms.ChoiceField(choices=[])
    model = forms.CharField(required=False, help_text="Vazio = default do provider.")
    prompt_structure = forms.ChoiceField(choices=[
        ("V1", "V1 - single user message (Li 2024)"),
        ("V2", "V2 - system + user (Dennstadt 2024)"),
    ])
    temperature = forms.FloatField(initial=0.0, min_value=0.0, max_value=2.0)
    max_tokens = forms.IntegerField(initial=100, min_value=1, max_value=8000)
    no_think = forms.BooleanField(required=False, initial=True,
                                  help_text="Desliga o raciocinio (qwen3/DeepSeek). Recomendado.")

    def __init__(self, *args, provider_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].choices = provider_choices or []


class UploadForm(forms.Form):
    file = forms.FileField(help_text="Ficheiro .txt (Title:/Abstract:), .csv ou .xlsx (Citations Export).")


class SettingsForm(forms.Form):
    OPENAI_API_KEY = forms.CharField(
        required=False, label="OpenAI API key",
        widget=forms.PasswordInput(render_value=False, attrs={"placeholder": "sk-..."}))
    DEEPSEEK_API_KEY = forms.CharField(
        required=False, label="DeepSeek API key",
        widget=forms.PasswordInput(render_value=False, attrs={"placeholder": "sk-..."}))
    GROQ_API_KEY = forms.CharField(
        required=False, label="Groq API key",
        widget=forms.PasswordInput(render_value=False, attrs={"placeholder": "gsk_..."}))
    NCBI_API_KEY = forms.CharField(
        required=False, label="NCBI API key (opcional - acelera a extracao PubMed)")
    NCBI_EMAIL = forms.CharField(
        required=False, label="NCBI email (opcional - boa pratica nas E-utilities)")


class ExtractForm(forms.Form):
    query = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Query PubMed (sintaxe E-utilities).",
    )
    max_results = forms.IntegerField(initial=1000, min_value=1, max_value=10000)
    from_year = forms.IntegerField(required=False, min_value=1800, max_value=2100,
                                   help_text="Opcional.")
    to_year = forms.IntegerField(required=False, min_value=1800, max_value=2100,
                                 help_text="Opcional.")

    def clean(self):
        cleaned = super().clean()
        fy, ty = cleaned.get("from_year"), cleaned.get("to_year")
        if fy and ty and fy > ty:
            raise forms.ValidationError("O ano inicial nao pode ser maior do que o final.")
        return cleaned
