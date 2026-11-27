(function () {
    let activePicker;
    const pad = (number) => String(number).padStart(2, '0');
    const choices = {
        hours: Array.from({ length: 12 }, (_, index) => [index + 1, pad(index + 1)]),
        minutes: Array.from({ length: 60 }, (_, index) => [index, pad(index)]),
        period: [['AM', 'a. m.'], ['PM', 'p. m.']],
    };

    window.cerrarRelojesSala = () => activePicker?.close();

    document.querySelectorAll('[data-time-picker]').forEach((picker) => {
        const input = picker.querySelector('input[type="time"]');
        const trigger = picker.querySelector('[data-time-trigger]');
        const label = picker.querySelector('[data-time-label]');
        const popover = picker.querySelector('.sala-time-popover--compact');
        if (!input || !trigger || !label || !popover) return;

        const field = picker.closest('.sala-form-field');
        const error = field?.querySelector('[data-time-error]');

        input.required = false;
        input.tabIndex = -1;
        input.setAttribute('aria-hidden', 'true');
        popover.id = input.id + '-time-popover';
        trigger.setAttribute('aria-controls', popover.id);

        let openList;
        function closeList() {
            if (!openList) return;
            const { list, button } = openList;
            openList = undefined;
            list.hidden = true;
            button.setAttribute('aria-expanded', 'false');
            position();
        }

        function createChoiceField(key) {
            const container = popover.querySelector(`[data-time-list="${key}"]`);
            const button = container.querySelector('[data-time-list-trigger]');
            const list = container.querySelector('.sala-time-list-options');
            const buttonLabel = button.querySelector('span');
            const fieldLabel = list.getAttribute('aria-label');
            list.id = `${popover.id}-${key}`;
            button.setAttribute('aria-controls', list.id);
            let selected;

            function choose(option) {
                selected?.setAttribute('aria-pressed', 'false');
                selected = option;
                selected.setAttribute('aria-pressed', 'true');
                buttonLabel.textContent = option.textContent;
                button.setAttribute('aria-label', `${fieldLabel}: ${option.textContent}`);
            }

            const options = new Map(choices[key].map(([value, text]) => {
                const option = document.createElement('button');
                option.type = 'button';
                option.value = value;
                option.textContent = text;
                option.setAttribute('aria-pressed', 'false');
                option.addEventListener('click', () => {
                    choose(option);
                    closeList();
                    button.focus({ preventScroll: true });
                });
                list.append(option);
                return [value, option];
            }));

            button.addEventListener('click', () => {
                const wasOpen = openList?.list === list;
                closeList();
                if (wasOpen) return;
                openList = { list, button };
                list.hidden = false;
                button.setAttribute('aria-expanded', 'true');
                position();
                list.scrollTop = Math.max(0, selected.offsetTop - selected.offsetHeight);
                selected.focus({ preventScroll: true });
            });

            list.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    closeList();
                    button.focus({ preventScroll: true });
                }
                const next = {
                    ArrowDown: event.target.nextElementSibling,
                    ArrowUp: event.target.previousElementSibling,
                    Home: list.firstElementChild,
                    End: list.lastElementChild,
                }[event.key];
                if (next) {
                    event.preventDefault();
                    next.focus();
                }
            });
            container.addEventListener('focusout', (event) => {
                if (openList?.list === list && !container.contains(event.relatedTarget)) closeList();
            });

            return { button, setValue: (value) => choose(options.get(value)), getValue: () => selected.value };
        }

        const hours = createChoiceField('hours');
        const minutes = createChoiceField('minutes');
        const period = createChoiceField('period');

        function syncValue() {
            const [hour, minute] = input.value.split(':').map(Number);
            hours.setValue(hour % 12 || 12);
            minutes.setValue(minute || 0);
            period.setValue(hour >= 12 ? 'PM' : 'AM');
            label.textContent = input.value
                ? `${pad(hours.getValue())}:${pad(minutes.getValue())} ${period.getValue() === 'PM' ? 'p. m.' : 'a. m.'}`
                : 'Selecciona una hora';
        }

        function close() {
            popover.hidden = true;
            closeList();
            trigger.setAttribute('aria-expanded', 'false');
            if (activePicker === controls) activePicker = undefined;
        }

        function position() {
            if (popover.hidden) return;
            const rect = trigger.getBoundingClientRect();
            const popupRect = popover.getBoundingClientRect();
            const listBottom = openList?.list.getBoundingClientRect().bottom ?? popupRect.bottom;
            const height = Math.max(popupRect.height, listBottom - popupRect.top);
            const left = Math.min(rect.right - popupRect.width, document.documentElement.clientWidth - popupRect.width - 12);
            const below = rect.bottom + 8;
            const above = rect.top - height - 8;
            const top = below + height <= window.innerHeight - 12
                ? below : above >= 12 ? above : window.innerHeight - height - 12;
            popover.style.left = `${Math.max(12, left)}px`;
            popover.style.top = `${Math.max(12, top)}px`;
        }

        const controls = { close, position, trigger, popover };
        trigger.addEventListener('click', () => {
            if (!popover.hidden) {
                close();
                return;
            }
            window.cerrarRelojesSala();
            window.cerrarCalendariosSala?.();
            syncValue();
            document.body.append(popover);
            activePicker = controls;
            popover.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            position();
            hours.button.focus();
        });

        popover.querySelector('[data-time-apply]').addEventListener('click', () => {
            const hour = Number(hours.getValue()) % 12 + (period.getValue() === 'PM' ? 12 : 0);
            input.value = `${pad(hour)}:${pad(minutes.getValue())}`;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            field?.classList.remove('has-error');
            if (error) error.hidden = true;
            close();
            trigger.focus();
        });

        input.addEventListener('change', syncValue);
        syncValue();
    });

    function closeOutside(event) {
        if (!activePicker || activePicker.popover.contains(event.target) || activePicker.trigger.contains(event.target)) return;
        activePicker.close();
    }

    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('focusin', closeOutside);
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape' || !activePicker || activePicker.popover.hidden) return;
        const { close, trigger } = activePicker;
        close();
        trigger.focus();
    });
    window.addEventListener('resize', () => activePicker?.position());
    window.addEventListener('scroll', () => activePicker?.position(), true);
})();
