from django.test import TestCase
from django.urls import reverse

from .forms import RegistroUsuarioForm
from .models import UsuarioSistema


class LoginViewTests(TestCase):
    def test_login_page_is_available(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inicio/login.html')

    def test_valid_credentials_open_the_home_page(self):
        password = 'Prueba-segura-123'
        UsuarioSistema.objects.create_user(username='operador', password=password)

        response = self.client.post(reverse('login'), {
            'usuario': 'operador',
            'contrasena': password,
        })

        self.assertRedirects(response, reverse('homePage'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_invalid_credentials_show_an_error(self):
        response = self.client.post(reverse('login'), {
            'usuario': 'inexistente',
            'contrasena': 'incorrecta',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usuario o contraseña incorrectos.')


class HomePageViewTests(TestCase):
    def test_home_page_requires_authentication(self):
        response = self.client.get(reverse('homePage'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('homePage')}")

    def test_authenticated_user_can_open_home_page(self):
        user = UsuarioSistema.objects.create_user(
            username='operador',
            password='Prueba-segura-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('homePage'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inicio/homePage.html')


class RegistroUsuarioFormTests(TestCase):
    def test_form_hashes_password_before_saving_user(self):
        form = RegistroUsuarioForm(data={
            'username': 'nuevo_operador',
            'password': 'Prueba-segura-123',
            'rol': 'operador',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertTrue(user.check_password('Prueba-segura-123'))
        self.assertNotEqual(user.password, 'Prueba-segura-123')
        self.assertEqual(user.rol, 'operador')
