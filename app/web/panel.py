def pagina():
    return '''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Delay Audio</title>
  <link rel="stylesheet" href="/static/css/delay_audio.css?v=autoapertura-reflejo-tarjetas-20260620">
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
  <script src="/static/js/delay_audio.js?v=entrada-silenciosa-20260621"></script>
</body>
</html>'''.encode("utf-8")
