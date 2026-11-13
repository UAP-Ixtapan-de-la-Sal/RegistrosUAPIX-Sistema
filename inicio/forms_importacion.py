from django import forms

from .services.importacion_excel import MAX_FILE_SIZE


class ImportarExcelForm(forms.Form):
    archivo = forms.FileField(
        label='Archivo Excel',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}),
        help_text='Formato .xlsx, máximo 5 MB. Puedes cargar una o varias hojas con datos.',
    )

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if not archivo.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('Selecciona un archivo con extensión .xlsx.')
        if not archivo.size or archivo.size > MAX_FILE_SIZE:
            raise forms.ValidationError('El archivo debe contener datos y pesar como máximo 5 MB.')
        return archivo
