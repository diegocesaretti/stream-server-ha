play:
  name: Reproducir contenido Stremio
  description: Consulta todos los proveedores y reproduce el enlace ideal (1080p, más semillas y menor tamaño) o un índice concreto. En Cast puede agregar subtítulos automáticamente.
  fields:
    entry_id:
      name: Entrada
      required: false
      selector:
        config_entry:
          integration: stremio_stream_bridge
    media_type:
      name: Tipo
      description: Tipo Stremio, por ejemplo movie, series, tv, channel o sport.
      required: true
      selector:
        select:
          options:
            - movie
            - series
            - anime
            - tv
            - channel
            - sport
    media_id:
      name: ID de contenido
      description: ID IMDb o ID de episodio, por ejemplo tt0133093 o tt0903747:1:1.
      required: true
      selector:
        text:
    media_player:
      name: Reproductor
      description: Entidad de destino. Si se omite, usa la configurada por defecto.
      required: false
      selector:
        entity:
          domain: media_player
    profile:
      name: Perfil de proveedor
      description: General, Audio Latino o F1/Deportes. Los perfiles especiales reproducen sin subtítulos.
      required: false
      default: default
      selector:
        select:
          options:
            - default
            - latin
            - sports
    stream_index:
      name: Índice de stream
      description: Opcional. Si se omite, usa el filtro de enlace ideal configurado.
      required: false
      selector:
        number:
          min: 0
          max: 100
          step: 1
          mode: box
    disable_subtitles:
      name: Desactivar subtítulos
      description: Ignora los subtítulos automáticos sólo para esta reproducción.
      required: false
      default: false
      selector:
        boolean:

play_url:
  name: Reproducir URL o magnet
  description: Envía una URL HTTP(S) o convierte un magnet mediante stream-server.
  fields:
    entry_id:
      name: Entrada
      required: false
      selector:
        config_entry:
          integration: stremio_stream_bridge
    url:
      name: URL
      required: true
      selector:
        text:
          multiline: true
    media_player:
      name: Reproductor
      required: false
      selector:
        entity:
          domain: media_player

search:
  name: Buscar en catálogos
  description: Guarda una búsqueda de Cinemeta para verla luego en Multimedia. Útil en versiones de Home Assistant sin búsqueda nativa de media_source.
  fields:
    entry_id:
      name: Entrada
      required: false
      selector:
        config_entry:
          integration: stremio_stream_bridge
    query:
      name: Búsqueda
      required: true
      selector:
        text:
    media_type:
      name: Tipo
      required: false
      default: all
      selector:
        select:
          options:
            - all
            - movie
            - series

refresh:
  name: Actualizar conexión
  description: Fuerza una comprobación del stream-server y de todos los manifiestos.
  fields:
    entry_id:
      name: Entrada
      required: false
      selector:
        config_entry:
          integration: stremio_stream_bridge

subtitle_diagnostics:
  name: Diagnosticar subtítulos
  description: Comprueba proveedor, idioma, conversión WebVTT, URL LAN y compatibilidad Cast sin iniciar la reproducción.
  fields:
    entry_id:
      name: Entrada
      required: false
      selector:
        config_entry:
          integration: stremio_stream_bridge
    media_type:
      name: Tipo
      description: movie o series.
      required: true
      selector:
        select:
          options:
            - movie
            - series
    media_id:
      name: ID de contenido
      description: Por ejemplo tt0133093 o tt0903747:1:1.
      required: true
      selector:
        text:
    media_player:
      name: Reproductor
      description: Entidad Cast a comprobar. Si se omite, usa la predeterminada.
      required: false
      selector:
        entity:
          domain: media_player
    stream_index:
      name: Índice de stream
      description: Opcional. Si se omite, usa el enlace ideal.
      required: false
      selector:
        number:
          min: 0
          max: 100
          step: 1
          mode: box
