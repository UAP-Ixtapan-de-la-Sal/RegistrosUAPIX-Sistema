(function () {
    const dialog = document.querySelector('.app-confirm-dialog');
    const title = dialog?.querySelector('#appConfirmTitle');
    const message = dialog?.querySelector('#appConfirmMessage');
    const acceptButton = dialog?.querySelector('[data-confirm-accept]');
    const cancelButton = dialog?.querySelector('[data-confirm-cancel]');

    window.confirmarAccion = function (confirmationMessage, options) {
        const settings = options || {};
        if (!dialog || !title || !message || !acceptButton || !cancelButton) {
            return Promise.reject(new Error('No se encontró el diálogo de confirmación.'));
        }
        if (dialog.open) {
            return Promise.reject(new Error('Ya hay una confirmación abierta.'));
        }

        title.textContent = settings.title || '¿Confirmas esta acción?';
        message.textContent = confirmationMessage;
        acceptButton.textContent = settings.acceptText || 'Confirmar';
        dialog.classList.toggle('is-danger', Boolean(settings.danger));

        return new Promise(function (resolve) {
            let settled = false;

            function finish(accepted) {
                if (settled) return;
                settled = true;
                acceptButton.removeEventListener('click', accept);
                cancelButton.removeEventListener('click', cancel);
                dialog.removeEventListener('cancel', cancelDialog);
                dialog.removeEventListener('click', cancelBackdrop);
                if (dialog.open) dialog.close();
                resolve(accepted);
            }

            function accept() {
                finish(true);
            }

            function cancel() {
                finish(false);
            }

            function cancelDialog(event) {
                event.preventDefault();
                cancel();
            }

            function cancelBackdrop(event) {
                if (event.target === dialog) cancel();
            }

            acceptButton.addEventListener('click', accept);
            cancelButton.addEventListener('click', cancel);
            dialog.addEventListener('cancel', cancelDialog);
            dialog.addEventListener('click', cancelBackdrop);
            dialog.showModal();
            acceptButton.focus();
        });
    };
})();
