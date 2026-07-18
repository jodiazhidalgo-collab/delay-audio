import json
import os


def _path_config():
    data_root = os.environ.get("DELAY_AUDIO_DATA_ROOT", "/data")
    media_root = os.environ.get("DELAY_AUDIO_MEDIA_ROOT", "/media")
    downloads_root = os.environ.get("DELAY_AUDIO_DOWNLOADS_ROOT", f"{data_root}/downloads/torrents")
    complete_root = os.environ.get("DELAY_AUDIO_COMPLETE_ROOT", f"{downloads_root}/complete")
    queue_root = os.environ.get("DELAY_AUDIO_QUEUE_ROOT", f"{downloads_root}/queue")
    return {
        "queueMoviesPath": os.environ.get("DELAY_AUDIO_QUEUE_MOVIES_PATH", f"{queue_root}/movies"),
        "completeMoviesPath": os.environ.get("DELAY_AUDIO_COMPLETE_MOVIES_PATH", f"{complete_root}/movies"),
        "mediaRootPath": media_root,
        "hospitalPath": os.environ.get("DELAY_AUDIO_MEDIA_HOSPITAL_PATH", f"{media_root}/Hospital"),
    }


def pagina():
    path_config = json.dumps(_path_config(), ensure_ascii=False)
    return f'''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Delay Audio</title>
  <link rel="stylesheet" href="/static/css/delay_audio.css?v=resultado-hibrido-fase6-20260710">
</head>
<body>
  <main class="shell">
    <header class="top">
      <div class="top-main">
        <div class="top-title">
          <h1>Delay Audio</h1>
          <button id="renameModeButton" class="rename-mode-button" type="button" aria-pressed="false">&#9998; Renombrar</button>
          <p id="statusText" class="sr-status" aria-live="polite">Cargando...</p>
        </div>
        <div id="headerWorkshopCluster" class="header-workshop-cluster" aria-live="polite"></div>
      </div>
      <button class="icon-button" id="refreshButton" aria-label="Actualizar">&#8635;</button>
    </header>

    <nav id="tabs" class="tabs" aria-label="Secciones"></nav>
    <section id="folders" class="folders" aria-live="polite"></section>
  </main>

  <script src="/static/js/entry_sound.js?v=entrada-silenciosa-20260621"></script>
  <script src="/static/js/delay_audio_sounds.js?v=sonido-final-procesos-20260619"></script>
  <script>window.DelayAudioConfig = {path_config};</script>
  <script src="/static/js/delay_audio.js?v=resultado-hibrido-fase6-20260710"></script>
</body>
</html>'''.encode("utf-8")
