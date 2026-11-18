(() => {
  const input = document.getElementById('id_image');
  const preview = document.getElementById('photo-preview');
  const image = document.getElementById('photo-preview-image');
  let url;
  input?.addEventListener('change', () => {
    if (url) URL.revokeObjectURL(url);
    const file = input.files?.[0];
    if (!file || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      preview.hidden = true;
      image.removeAttribute('src');
      return;
    }
    url = URL.createObjectURL(file);
    image.src = url;
    preview.hidden = false;
  });
  document.getElementById('photo-upload-form')?.addEventListener('submit', () => {
    document.getElementById('photo-upload-button').disabled = true;
    document.getElementById('photo-upload-status').textContent = 'Uploading your photo. Please keep this page open.';
  });
  window.addEventListener('pagehide', () => { if (url) URL.revokeObjectURL(url); });
})();
