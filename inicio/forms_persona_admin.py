from django import forms

from .models import PERFILES_PERSONA, Persona


class PersonaAdminForm(forms.ModelForm):
    perfiles_institucionales = forms.MultipleChoiceField(
        label='Perfiles institucionales', choices=PERFILES_PERSONA,
        required=False, widget=forms.CheckboxSelectMultiple,
        help_text='Selecciona todos los perfiles que correspondan. El perfil principal siempre se conserva entre ellos.',
    )

    class Meta:
        model = Persona
        fields = '__all__'
        labels = {'perfil': 'Perfil principal'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['perfiles_institucionales'] = sorted(self.instance.perfiles_actuales)

    def clean(self):
        data = super().clean()
        perfiles = set(data.get('perfiles_institucionales', []))
        if data.get('perfil'):
            perfiles.add(data['perfil'])
        data['perfiles_institucionales'] = perfiles
        return data
