(function () {
    if (typeof window.flatpickr !== 'function') return;

    document.querySelectorAll('[data-date-range-picker]').forEach((picker) => {
        const display = picker.querySelector('[data-range-display]');
        const start = picker.querySelector('[data-range-start]');
        const end = picker.querySelector('[data-range-end]');
        const panel = picker.querySelector('.date-range-panel');
        const presets = panel.querySelectorAll('[data-range-preset]');
        const calendarView = panel.querySelector('.date-calendar-view');
        let activePreset = start.value ? 'today' : 'custom';

        function committedDates() {
            return start.value && end.value ? [start.value, end.value] : [];
        }

        const calendar = window.flatpickr(display, {
            mode: 'range',
            showMonths: 2,
            dateFormat: 'Y-m-d',
            defaultDate: committedDates(),
            locale: window.flatpickr.l10ns.es,
            clickOpens: false,
            inline: true,
            disableMobile: true,
            appendTo: calendarView,
            onChange(dates) {
                if (dates.length === 2) commit(dates, 'custom');
                else renderDisplay();
            },
        });
        calendarView.append(calendar.calendarContainer);
        document.body.append(panel);

        function renderDisplay() {
            const format = (date) => date.split('-').reverse().join('/');
            display.value = start.value === end.value
                ? format(start.value)
                : format(start.value) + ' – ' + format(end.value);
            presets.forEach((button) => {
                const active = button.dataset.rangePreset === activePreset;
                button.classList.toggle('active', active);
                button.setAttribute('aria-pressed', String(active));
            });
        }

        function positionPanel() {
            if (panel.classList.contains('is-hidden')) return;
            const anchor = display.getBoundingClientRect();
            const margin = 12;
            const below = anchor.bottom + 10;
            const left = Math.max(margin, Math.min(anchor.left, window.innerWidth - panel.offsetWidth - margin));
            const top = below + panel.offsetHeight <= window.innerHeight - margin
                ? below
                : Math.max(margin, anchor.top - panel.offsetHeight - 10);
            panel.style.left = left + 'px';
            panel.style.top = top + 'px';
        }

        function close(restoreFocus = false) {
            panel.classList.add('is-hidden');
            display.setAttribute('aria-expanded', 'false');
            calendar.setDate(committedDates(), false);
            renderDisplay();
            if (restoreFocus) display.focus();
        }

        function toggle() {
            if (!panel.classList.contains('is-hidden')) {
                close();
                return;
            }
            panel.classList.remove('is-hidden');
            display.setAttribute('aria-expanded', 'true');
            calendar.redraw();
            positionPanel();
        }

        function commit(dates, preset) {
            start.value = dates[0] ? calendar.formatDate(dates[0], 'Y-m-d') : '';
            end.value = dates[1] ? calendar.formatDate(dates[1], 'Y-m-d') : '';
            activePreset = preset;
            close(true);
            start.dispatchEvent(new Event('change', { bubbles: true }));
        }

        presets.forEach((button) => button.addEventListener('click', () => {
            const preset = button.dataset.rangePreset;
            if (preset === 'custom') {
                activePreset = 'custom';
                calendar.clear(false);
                renderDisplay();
                calendar.calendarContainer.querySelector('.flatpickr-day:not(.prevMonthDay):not(.nextMonthDay)')?.focus();
                return;
            }
            if (preset === 'clear') {
                commit([], 'custom');
                return;
            }

            const from = new Date();
            from.setHours(0, 0, 0, 0);
            const to = new Date(from);
            if (preset === 'yesterday') {
                from.setDate(from.getDate() - 1);
                to.setTime(from.getTime());
            } else if (preset === 'last7') {
                from.setDate(from.getDate() - 6);
            } else if (preset === 'week') {
                from.setDate(from.getDate() - (from.getDay() + 6) % 7);
            }
            commit([from, to], preset);
        }));

        display.addEventListener('click', toggle);
        display.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'ArrowDown') return;
            event.preventDefault();
            toggle();
            if (!panel.classList.contains('is-hidden')) presets[0].focus();
        });
        document.addEventListener('pointerdown', (event) => {
            if (!panel.classList.contains('is-hidden') && !picker.contains(event.target) && !panel.contains(event.target)) close();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !panel.classList.contains('is-hidden')) close(true);
        });
        window.addEventListener('resize', positionPanel);
        window.addEventListener('scroll', positionPanel, true);
        renderDisplay();
    });
})();
