(function() {
    const dateLabelFormat = new Intl.DateTimeFormat('es-MX', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
    const monthLabelFormat = new Intl.DateTimeFormat('es-MX', {
        month: 'long',
        year: 'numeric'
    });
    const closeCalendars = new Map();

    function parseIsoDate(value) {
        if (!value) return null;
        const parts = value.split('-').map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }

    function formatIsoDate(date) {
        return [
            date.getFullYear(),
            String(date.getMonth() + 1).padStart(2, '0'),
            String(date.getDate()).padStart(2, '0')
        ].join('-');
    }

    function initializeCalendar(picker) {
        if (picker.dataset.salaCalendarReady) return;
        const input = picker.querySelector('input[type="hidden"]');
        const trigger = picker.querySelector('[data-sala-date-trigger]');
        const label = picker.querySelector('[data-sala-date-label]');
        const popover = picker.querySelector('.sala-calendar-popover');
        const monthHeading = picker.querySelector('[data-sala-date-month]');
        const daysGrid = picker.querySelector('[data-sala-date-days]');
        if (!input || !trigger || !label || !popover || !monthHeading || !daysGrid) return;

        picker.dataset.salaCalendarReady = 'true';
        let selectedMonth = parseIsoDate(input.value) || new Date();
        selectedMonth = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth(), 1);
        popover.id = input.id + '-calendar-popover';
        trigger.setAttribute('aria-controls', popover.id);

        function closeCalendar(returnFocus) {
            popover.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            if (returnFocus) trigger.focus();
        }
        closeCalendars.set(popover, closeCalendar);

        function updateLabel() {
            const date = parseIsoDate(input.value);
            label.textContent = date ? dateLabelFormat.format(date) : 'Selecciona una fecha';
        }

        function setDate(date) {
            input.value = date ? formatIsoDate(date) : '';
            updateLabel();
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            closeCalendar(true);
        }

        function renderCalendar() {
            monthHeading.textContent = monthLabelFormat.format(selectedMonth);
            daysGrid.replaceChildren();
            const firstOfMonth = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth(), 1);
            const mondayOffset = (firstOfMonth.getDay() + 6) % 7;
            const selectedDate = parseIsoDate(input.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            for (let index = 0; index < 42; index += 1) {
                const date = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth(), index - mondayOffset + 1);
                const dayButton = document.createElement('button');
                dayButton.type = 'button';
                dayButton.className = 'sala-calendar-day';
                dayButton.textContent = String(date.getDate());
                dayButton.setAttribute('aria-label', dateLabelFormat.format(date));
                if (date.getMonth() !== selectedMonth.getMonth()) dayButton.classList.add('is-outside-month');
                if (date.toDateString() === today.toDateString()) dayButton.classList.add('is-today');
                if (selectedDate && date.toDateString() === selectedDate.toDateString()) {
                    dayButton.classList.add('is-selected');
                    dayButton.setAttribute('aria-pressed', 'true');
                }
                dayButton.addEventListener('click', function() { setDate(date); });
                daysGrid.appendChild(dayButton);
            }
        }

        function positionPopover() {
            if (popover.hidden) return;
            const rect = trigger.getBoundingClientRect();
            const popup = popover.getBoundingClientRect();
            const margin = 12;
            const left = Math.max(margin, Math.min(rect.left, window.innerWidth - popup.width - margin));
            const below = rect.bottom + 8;
            const top = below + popup.height <= window.innerHeight - margin
                ? below
                : Math.max(margin, rect.top - popup.height - 8);
            popover.style.left = left + 'px';
            popover.style.top = top + 'px';
        }

        picker.querySelector('[data-sala-date-prev]').addEventListener('click', function() {
            selectedMonth = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth() - 1, 1);
            renderCalendar();
        });
        picker.querySelector('[data-sala-date-next]').addEventListener('click', function() {
            selectedMonth = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth() + 1, 1);
            renderCalendar();
        });

        const clearButton = picker.querySelector('[data-sala-date-clear]');
        if (clearButton) clearButton.addEventListener('click', function() { setDate(null); });
        const todayButton = picker.querySelector('[data-sala-date-today]');
        if (todayButton) todayButton.addEventListener('click', function() { setDate(new Date()); });

        trigger.addEventListener('click', function() {
            if (!popover.hidden) {
                closeCalendar(false);
                return;
            }
            closeCalendars.forEach(function(close, other) {
                if (other !== popover && !other.hidden) close(false);
            });
            const value = parseIsoDate(input.value);
            if (value) selectedMonth = new Date(value.getFullYear(), value.getMonth(), 1);
            renderCalendar();
            document.body.appendChild(popover);
            popover.classList.add('is-viewport-positioned');
            popover.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            positionPopover();
        });

        popover.addEventListener('keydown', function(event) {
            if (event.key === 'Escape' && !popover.hidden) closeCalendar(true);
        });
        window.addEventListener('resize', positionPopover);
        window.addEventListener('scroll', positionPopover, true);
        updateLabel();
    }

    document.querySelectorAll('[data-sala-date-picker]').forEach(initializeCalendar);
    function closePickersExceptCurrent(event) {
        const target = event.target;
        if (!(target instanceof Element)) return;

        document.querySelectorAll('[data-sala-date-picker]').forEach(function(picker) {
            const trigger = picker.querySelector('[data-sala-date-trigger]');
            const popoverId = trigger && trigger.getAttribute('aria-controls');
            const popover = popoverId && document.getElementById(popoverId);
            if (!popover || popover.hidden || picker.contains(target) || popover.contains(target)) return;
            closeCalendars.get(popover)(false);
        });

        document.querySelectorAll('.sala-time-popover').forEach(function(popover) {
            if (popover.hidden || popover.contains(target)) return;
            const trigger = document.querySelector('[aria-controls="' + popover.id + '"]');
            const picker = trigger && trigger.closest('[data-time-picker]');
            if (picker && picker.contains(target)) return;
            popover.hidden = true;
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
        });
    }

    document.addEventListener('pointerdown', closePickersExceptCurrent, true);
    document.addEventListener('focusin', closePickersExceptCurrent, true);
})();
