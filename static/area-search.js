(() => {
  const picker = document.querySelector('[data-area-picker]');
  if (!picker) return;
  const state = picker.querySelector('[name="state"]');
  const query = picker.querySelector('[name="q"]');
  const target = document.getElementById(picker.dataset.target);
  const status = document.getElementById('area-search-status');
  let timer, controller, generation = 0;
  async function update() {
    const current = ++generation;
    controller?.abort();
    controller = new AbortController();
    status.textContent = 'Looking for cities…';
    try {
      const params = new URLSearchParams({state: state.value, q: query.value});
      const response = await fetch('/neighbors/areas/?' + params, {signal: controller.signal});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (current !== generation) return;
      const previous = target.value;
      target.replaceChildren(new Option('Choose a matching city', ''));
      data.areas.forEach(area => target.add(new Option(area.name, area[picker.dataset.areaValue])));
      if ([...target.options].some(option => option.value === previous)) target.value = previous;
      status.textContent = data.limited ? 'Showing the first 40 matches. Type more of the city name to narrow your search.' : `${data.areas.length} matching cities. Choose your city from the area list.`;
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = 'City search could not load. Use the Search cities or Find neighbors button to try again.';
    }
  }
  query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(update, 250); });
  state.addEventListener('change', () => { clearTimeout(timer); update(); });
  window.addEventListener('pagehide', () => { clearTimeout(timer); controller?.abort(); });
})();
