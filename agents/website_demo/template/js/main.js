document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('.nav-toggle');
  const links = document.querySelector('.nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', () => links.classList.toggle('is-open'));
  }

  const form = document.getElementById('booking-form');
  const confirmation = document.getElementById('form-confirmation');
  if (form && confirmation) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      form.style.display = 'none';
      confirmation.classList.add('is-visible');
    });
  }
});
