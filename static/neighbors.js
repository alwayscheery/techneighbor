(() => {
  const button = document.getElementById('load-neighbor-map');
  if (!button) return;
  const config = JSON.parse(document.getElementById('neighbor-map-config').textContent);
  const status = document.getElementById('map-status');
  const container = document.getElementById('neighbor-map');
  let timer;
  const fail = () => {
    clearTimeout(timer);
    container.hidden = true;
    status.textContent = 'The in-app map could not load. You can still browse neighbors or use Open Google Maps below.';
  };
  window.gm_authFailure = fail;
  window.initNeighborMap = async () => {
    try {
      const {Map} = await google.maps.importLibrary('maps');
      const {AdvancedMarkerElement} = await google.maps.importLibrary('marker');
      clearTimeout(timer);
      container.hidden = false;
      const center = config.center || config.points[0] || {lat: 0, lng: 0};
      const map = new Map(container, {center, zoom: config.center ? 12 : 9, mapId: config.mapId,
        streetViewControl: false, mapTypeControl: false, fullscreenControl: true, gestureHandling: 'cooperative'});
      const bounds = new google.maps.LatLngBounds();
      config.points.forEach(point => {
        const position = {lat: point.lat, lng: point.lng};
        const title = `${point.label}: ${point.count} listed profile${point.count === 1 ? '' : 's'}. General area only.`;
        const marker = new AdvancedMarkerElement({map, position, title, gmpClickable: true});
        marker.addListener('click', () => {
          const url = new URL(location.href);
          url.searchParams.set('area', point.slug);
          location.assign(url.pathname + url.search);
        });
        bounds.extend(position);
      });
      if (!config.center && config.points.length > 1) map.fitBounds(bounds, 40);
      if (!config.center && !config.points.length) map.setZoom(2);
      document.getElementById('map-intro').hidden = true;
      status.textContent = 'Google map loaded. Markers show general area centers, not home locations. Select an area marker to filter the profiles.';
    } catch (_) { fail(); }
  };
  button.addEventListener('click', () => {
    button.disabled = true;
    status.textContent = 'Loading Google Maps…';
    const params = new URLSearchParams({key: config.key, loading: 'async', callback: 'initNeighborMap', v: 'weekly', auth_referrer_policy: 'origin'});
    const script = document.createElement('script');
    script.src = 'https://maps.googleapis.com/maps/api/js?' + params.toString();
    script.async = true;
    script.onerror = fail;
    timer = setTimeout(fail, 20000);
    document.head.appendChild(script);
  }, {once: true});
})();
