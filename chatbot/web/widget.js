/**
 * Chat flotante del Asistente Univalle.
 *
 * Se instala con una línea en cualquier página:
 *   <script src="https://SERVIDOR/widget.js" defer></script>
 *
 * Opciones (atributos de esa etiqueta):
 *   data-color     color principal (por defecto, rojo vino institucional)
 *   data-perfil    "aspirante" o "estudiante" para saltar la pregunta inicial (útil en el sitio de Admisiones)
 *   data-etiqueta  texto bajo el nombre; vacío para quitarlo
 *
 * Corre dentro de un Shadow DOM para que los estilos del sitio y los del chat no se afecten entre sí, y nunca
 * interpreta HTML en los mensajes: todo se pinta como texto.
 */
(function () {
  'use strict';
  if (window.__asistenteUnivalle) return;
  window.__asistenteUnivalle = true;

  var script = document.currentScript;
  var API = new URL(script.src).origin;
  var COLOR = script.dataset.color || '#7a0c2e';
  var ETIQUETA = script.dataset.etiqueta === undefined ? 'Prototipo de demostración' : script.dataset.etiqueta;
  var PERFIL_FIJO = script.dataset.perfil === 'aspirante' || script.dataset.perfil === 'estudiante' ? script.dataset.perfil : null;
  var ESPERA_MS = 35000;
  var AVISO_ESPERA_MS = 6000;
  var MAX_HISTORIAL = 6;
  var VALORABLES = { aprobada: 1, novedades: 1, ia: 1, norma: 1, calendario: 1, sin_informacion: 1, personal: 1 };

  var ESTILOS = [
    ':host{--primario:' + COLOR + ';--texto:#1f2328;--suave:#5b6470;--borde:#e3e5e8;--fondo:#fff;--fondo-mensajes:#f7f7f8;--burbuja:#fff;--aviso:#fdf3dc;--aviso-texto:#5f4000}',
    '@media (prefers-color-scheme:dark){:host{--texto:#e8eaed;--suave:#a5adb8;--borde:#3a3f46;--fondo:#1d2024;--fondo-mensajes:#16181b;--burbuja:#24282d;--aviso:#3d3218;--aviso-texto:#f5dfa8}}',
    '.panel,.lanzador{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:15px;line-height:1.45;color:var(--texto)}',
    '*{box-sizing:border-box}',
    'button{font:inherit;cursor:pointer}',
    '.lanzador{position:fixed;right:20px;bottom:20px;z-index:2147483000;display:flex;align-items:center;gap:8px;height:52px;padding:0 18px 0 14px;border:0;border-radius:26px;background:var(--primario);color:#fff;font-weight:600;box-shadow:0 6px 20px rgba(0,0,0,.25);transition:transform .15s}',
    '.lanzador:hover{transform:translateY(-2px)}',
    '.lanzador svg{width:24px;height:24px;flex:none}',
    '.panel{position:fixed;right:20px;bottom:20px;z-index:2147483000;display:flex;flex-direction:column;width:400px;height:min(660px,calc(100vh - 40px));background:var(--fondo);border-radius:16px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.3)}',
    '.panel[hidden],.lanzador[hidden],.banda[hidden]{display:none}',
    'header{display:flex;align-items:center;gap:10px;padding:13px 12px 13px 16px;background:var(--primario);color:#fff}',
    'header div{flex:1;min-width:0}',
    'h2{margin:0;font-size:15.5px;font-weight:650}',
    'header small{display:block;font-size:12px;opacity:.88}',
    '.icono{display:grid;place-items:center;width:34px;height:34px;border:0;border-radius:8px;background:transparent;color:#fff}',
    '.icono:hover{background:rgba(255,255,255,.16)}',
    '.icono svg{width:19px;height:19px}',
    '.banda{display:block;padding:9px 14px;background:var(--aviso);color:var(--aviso-texto);font-size:13px;text-decoration:none;border-bottom:1px solid var(--borde)}',
    '.banda strong{font-weight:650}',
    '.mensajes{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:12px;background:var(--fondo-mensajes)}',
    '.msg{max-width:88%;padding:10px 13px;border-radius:14px;overflow-wrap:anywhere}',
    '.msg p{margin:0 0 7px}.msg p:last-child{margin:0}',
    '.msg ul,.msg ol{margin:0 0 7px;padding-left:20px}.msg ul:last-child,.msg ol:last-child{margin:0}',
    '.msg li{margin-bottom:3px}',
    '.msg a{color:var(--primario);text-decoration:underline;text-underline-offset:2px;overflow-wrap:anywhere}',
    '@media (prefers-color-scheme:dark){.msg a,.fuentes a{color:#f1a7bb}}',
    '.bot{align-self:flex-start;background:var(--burbuja);border:1px solid var(--borde);border-bottom-left-radius:4px}',
    '.yo{align-self:flex-end;background:var(--primario);color:#fff;border-bottom-right-radius:4px}',
    '.fuentes{margin-top:9px;padding-top:8px;border-top:1px solid var(--borde);font-size:12.5px;color:var(--suave)}',
    '.fuentes a{color:var(--primario);font-weight:600}',
    '.fuentes span+span::before{content:" · "}',
    '.nota-ia{margin-top:5px;font-size:11.5px}',
    '.valorar{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:12.5px;color:var(--suave)}',
    '.valorar button{padding:2px 10px;border:1px solid var(--borde);border-radius:12px;background:transparent;color:var(--suave);font-size:12.5px}',
    '.valorar button:hover{border-color:var(--primario);color:var(--primario)}',
    '.opciones{display:flex;flex-direction:column;gap:7px;align-self:stretch}',
    '.opcion{padding:9px 12px;border:1px solid var(--borde);border-radius:10px;background:var(--burbuja);color:var(--texto);text-align:left;font-size:14px}',
    '.opcion:hover{border-color:var(--primario);color:var(--primario)}',
    '.opcion.perfil{font-weight:600}',
    '.escribiendo{display:flex;gap:4px;align-items:center;height:21px}',
    '.escribiendo i{width:7px;height:7px;border-radius:50%;background:#9aa1ab;animation:salto 1.2s infinite}',
    '.escribiendo i:nth-child(2){animation-delay:.15s}.escribiendo i:nth-child(3){animation-delay:.3s}',
    '.espera-texto{margin-top:6px;font-size:13px;color:var(--suave)}',
    '@keyframes salto{0%,60%,100%{transform:none;opacity:.5}30%{transform:translateY(-4px);opacity:1}}',
    'form{display:flex;gap:8px;padding:10px 12px;background:var(--fondo);border-top:1px solid var(--borde)}',
    'textarea{flex:1;min-width:0;max-height:96px;padding:9px 11px;border:1px solid var(--borde);border-radius:10px;font:inherit;color:var(--texto);background:var(--burbuja);resize:none;outline:0;overflow-y:hidden}',
    'textarea:focus,textarea:focus-visible{outline:0;border-color:var(--primario);box-shadow:0 0 0 2px color-mix(in srgb,var(--primario) 20%,transparent)}',
    '.enviar{display:grid;place-items:center;width:42px;height:42px;flex:none;border:0;border-radius:10px;background:var(--primario);color:#fff}',
    '.enviar:disabled{opacity:.45;cursor:default}',
    '.enviar svg{width:19px;height:19px}',
    '.pie{padding:0 14px 9px;background:var(--fondo);font-size:11.5px;color:var(--suave)}',
    '.pie a{color:inherit}',
    '.pie button{padding:0;border:0;background:none;color:inherit;text-decoration:underline;font-size:11.5px}',
    ':focus-visible{outline:2px solid var(--primario);outline-offset:2px}',
    'header :focus-visible{outline-color:#fff}',
    '@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;height:100dvh;border-radius:0}.lanzador{right:14px;bottom:14px}}',
    '@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}'
  ].join('');

  var ICONOS = {
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg>',
    cerrar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    reiniciar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
    enviar: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3.4 20.4 21 12 3.4 3.6l.1 6.5L15 12l-11.5 1.9z"/></svg>'
  };

  function el(etiqueta, clase, texto) {
    var nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
  }

  function guardado(clave, valor) {
    try {
      if (valor === undefined) return window.sessionStorage.getItem(clave);
      if (valor === null) window.sessionStorage.removeItem(clave);
      else window.sessionStorage.setItem(clave, valor);
    } catch (e) { /* almacenamiento bloqueado: el chat funciona igual */ }
    return null;
  }

  /** Convierte **negrita** y direcciones http en nodos, sin pasar nunca por innerHTML. */
  function enLinea(destino, texto) {
    texto.split(/\*\*(.+?)\*\*/g).forEach(function (parte, i) {
      if (!parte) return;
      if (i % 2) { destino.appendChild(el('strong', '', parte)); return; }
      parte.split(/(https?:\/\/[^\s)]+)/g).forEach(function (trozo, j) {
        if (!trozo) return;
        if (j % 2) {
          var enlace = el('a', '', trozo.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, ''));
          enlace.href = trozo;
          enlace.target = '_blank';
          enlace.rel = 'noopener';
          destino.appendChild(enlace);
        } else {
          destino.appendChild(document.createTextNode(trozo));
        }
      });
    });
  }

  /** Párrafos, listas numeradas y viñetas. */
  function pintarTexto(destino, texto) {
    var lista = null;
    var tipoLista = '';
    texto.split('\n').forEach(function (linea) {
      var numerada = linea.match(/^\s*\d+[.)]\s+(.*)$/);
      var vineta = linea.match(/^\s*[-•*]\s+(.*)$/);
      var item = numerada || vineta;
      if (item) {
        var tipo = numerada ? 'ol' : 'ul';
        if (!lista || tipoLista !== tipo) {
          lista = el(tipo);
          tipoLista = tipo;
          destino.appendChild(lista);
        }
        var li = el('li');
        enLinea(li, item[1]);
        lista.appendChild(li);
        return;
      }
      lista = null;
      if (linea.trim()) {
        var p = el('p');
        enLinea(p, linea);
        destino.appendChild(p);
      }
    });
  }

  var host = el('div');
  host.id = 'asistente-univalle';
  // Sin esto, reglas del sitio como «* { color: ... !important }» se heredan dentro del chat.
  host.style.setProperty('all', 'initial', 'important');
  var raiz = host.attachShadow({ mode: 'open' });
  var estilo = el('style');
  estilo.textContent = ESTILOS;
  raiz.appendChild(estilo);

  var lanzador = el('button', 'lanzador');
  lanzador.type = 'button';
  lanzador.setAttribute('aria-label', 'Abrir el asistente virtual');
  lanzador.setAttribute('aria-expanded', 'false');
  lanzador.innerHTML = ICONOS.chat;
  lanzador.appendChild(el('span', '', '¿Tienes dudas?'));

  var panel = el('section', 'panel');
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Asistente virtual');

  var cabecera = el('header');
  var identidad = el('div');
  var titulo = el('h2', '', 'Asistente Univalle');
  identidad.appendChild(titulo);
  if (ETIQUETA) identidad.appendChild(el('small', '', ETIQUETA));
  var botonReiniciar = el('button', 'icono');
  botonReiniciar.type = 'button';
  botonReiniciar.setAttribute('aria-label', 'Empezar de nuevo');
  botonReiniciar.title = 'Empezar de nuevo';
  botonReiniciar.innerHTML = ICONOS.reiniciar;
  var botonCerrar = el('button', 'icono');
  botonCerrar.type = 'button';
  botonCerrar.setAttribute('aria-label', 'Cerrar');
  botonCerrar.innerHTML = ICONOS.cerrar;
  cabecera.append(identidad, botonReiniciar, botonCerrar);

  var banda = el('a', 'banda');
  banda.hidden = true;
  banda.target = '_blank';
  banda.rel = 'noopener';

  var mensajes = el('div', 'mensajes');
  mensajes.setAttribute('role', 'log');
  mensajes.setAttribute('aria-live', 'polite');

  var formulario = el('form');
  var entrada = el('textarea');
  entrada.rows = 1;
  entrada.placeholder = 'Escribe tu pregunta…';
  entrada.setAttribute('aria-label', 'Tu pregunta');
  entrada.maxLength = 500;
  var enviar = el('button', 'enviar');
  enviar.type = 'submit';
  enviar.setAttribute('aria-label', 'Enviar');
  enviar.innerHTML = ICONOS.enviar;
  formulario.append(entrada, enviar);

  var pie = el('div', 'pie');
  pie.appendChild(document.createTextNode('Orientación general: confirma con la fuente oficial. No escribas datos personales. '));
  var enlacePolitica = el('a', '', 'Tratamiento de datos');
  enlacePolitica.target = '_blank';
  enlacePolitica.rel = 'noopener';
  pie.appendChild(enlacePolitica);

  panel.append(cabecera, banda, mensajes, formulario, pie);
  raiz.append(lanzador, panel);

  var config = { bienvenida: '', sugerencias: { aspirante: [], estudiante: [] } };
  var historial = [];
  var perfil = PERFIL_FIJO || guardado('asistente-perfil');
  var ocupado = false;
  var iniciado = false;

  function bajar() {
    mensajes.scrollTop = mensajes.scrollHeight;
  }

  function agregarUsuario(texto) {
    mensajes.appendChild(el('div', 'msg yo', texto));
    bajar();
  }

  function valorar(burbuja, pregunta, datos) {
    var caja = el('div', 'valorar');
    caja.appendChild(document.createTextNode('¿Te sirvió?'));
    [['Sí', true], ['No', false]].forEach(function (par) {
      var boton = el('button', '', par[0]);
      boton.type = 'button';
      boton.setAttribute('aria-label', par[1] ? 'Sí me sirvió' : 'No me sirvió');
      boton.addEventListener('click', function () {
        caja.textContent = par[1] ? '¡Gracias!' : 'Gracias. Usaremos esto para mejorar.';
        fetch(API + '/api/valoracion', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            pregunta: pregunta,
            tipo: datos.tipo,
            fuentes: (datos.fuentes || []).map(function (f) { return f.titulo; }).slice(0, 3),
            util: par[1]
          })
        }).catch(function () { /* la valoración es opcional */ });
      });
      caja.appendChild(boton);
    });
    burbuja.appendChild(caja);
  }

  function agregarBot(texto, datos, pregunta) {
    var burbuja = el('div', 'msg bot');
    pintarTexto(burbuja, texto);
    var fuentes = datos && datos.fuentes;
    if (fuentes && fuentes.length) {
      var piePuente = el('div', 'fuentes');
      piePuente.appendChild(document.createTextNode('Fuente: '));
      fuentes.forEach(function (fuente) {
        var item = el('span');
        if (/^https?:\/\//.test(fuente.url || '')) {
          var enlace = el('a', '', fuente.titulo);
          enlace.href = fuente.url;
          enlace.target = '_blank';
          enlace.rel = 'noopener';
          item.appendChild(enlace);
        } else {
          item.textContent = fuente.titulo;
        }
        piePuente.appendChild(item);
      });
      if (datos.tipo === 'ia') piePuente.appendChild(el('div', 'nota-ia', 'Redactado con IA a partir de las fuentes. Verifícalo en el enlace.'));
      burbuja.appendChild(piePuente);
    }
    if (datos && pregunta && VALORABLES[datos.tipo]) valorar(burbuja, pregunta, datos);
    mensajes.appendChild(burbuja);
    // Las respuestas largas se leen desde su inicio, no desde el final.
    mensajes.scrollTop = burbuja.offsetTop - mensajes.offsetTop - 10;
  }

  function quitarOpciones() {
    var cajas = mensajes.querySelectorAll('.opciones');
    for (var i = 0; i < cajas.length; i++) cajas[i].remove();
  }

  function opciones(lista, clase, alElegir) {
    var caja = el('div', 'opciones');
    lista.forEach(function (par) {
      var boton = el('button', 'opcion' + (clase ? ' ' + clase : ''), par[0]);
      boton.type = 'button';
      boton.addEventListener('click', function () { quitarOpciones(); alElegir(par[1]); });
      caja.appendChild(boton);
    });
    mensajes.appendChild(caja);
    bajar();
  }

  function mostrarSugerencias() {
    var lista = (config.sugerencias && config.sugerencias[perfil]) || [];
    if (!lista.length) return;
    opciones(lista.map(function (t) { return [t, t]; }), '', preguntar);
  }

  function elegirPerfil(valor) {
    perfil = valor;
    guardado('asistente-perfil', valor);
    agregarUsuario(valor === 'aspirante' ? 'Quiero estudiar en Univalle' : 'Ya soy estudiante');
    agregarBot(valor === 'aspirante'
      ? 'Perfecto. Te ayudo con inscripciones, admisión, requisitos y lo que necesitas al ser admitido. Puedes elegir una pregunta o escribir la tuya.'
      : 'Perfecto. Te ayudo con matrícula, reglamento, cancelaciones, reingresos, grados, certificados y novedades. Elige una pregunta o escribe la tuya.');
    mostrarSugerencias();
  }

  function bienvenida() {
    mensajes.textContent = '';
    historial = [];
    agregarBot(config.bienvenida || '¡Hola! Soy el asistente virtual de la Universidad del Valle. ¿En qué te ayudo?');
    if (perfil) {
      mostrarSugerencias();
    } else {
      opciones([['Quiero estudiar en Univalle', 'aspirante'], ['Ya soy estudiante', 'estudiante']], 'perfil', elegirPerfil);
    }
  }

  function preguntar(texto) {
    var limpio = texto.trim();
    if (limpio.length < 2 || ocupado) return;
    ocupado = true;
    enviar.disabled = true;
    quitarOpciones();
    agregarUsuario(limpio);
    entrada.value = '';
    ajustarAltura();

    var espera = el('div', 'msg bot');
    espera.setAttribute('aria-label', 'Escribiendo');
    var puntos = el('div', 'escribiendo');
    puntos.append(el('i'), el('i'), el('i'));
    espera.appendChild(puntos);
    mensajes.appendChild(espera);
    bajar();

    var control = new AbortController();
    var temporizador = setTimeout(function () { control.abort(); }, ESPERA_MS);
    var avisoEspera = setTimeout(function () {
      espera.appendChild(el('div', 'espera-texto', 'Estoy revisando las fuentes. Puede tardar unos segundos…'));
      bajar();
    }, AVISO_ESPERA_MS);

    fetch(API + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pregunta: limpio, historial: historial.slice(-MAX_HISTORIAL), perfil: perfil || null }),
      signal: control.signal
    })
      .then(function (respuesta) {
        return respuesta.json().then(function (datos) {
          if (!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'error');
          return datos;
        });
      })
      .then(function (datos) {
        espera.remove();
        agregarBot(datos.respuesta, datos, limpio);
        historial.push({ rol: 'usuario', texto: limpio }, { rol: 'asistente', texto: datos.respuesta.slice(0, 600) });
      })
      .catch(function (error) {
        espera.remove();
        var detalle = error && error.name !== 'AbortError' && error.message !== 'Failed to fetch' && error.message !== 'error' ? error.message : '';
        agregarBot(detalle || 'No pude conectarme en este momento. Inténtalo de nuevo en unos minutos.');
      })
      .finally(function () {
        clearTimeout(temporizador);
        clearTimeout(avisoEspera);
        ocupado = false;
        enviar.disabled = false;
        entrada.focus();
      });
  }

  function aplicarConfig(datos) {
    config = datos || config;
    if (config.nombre) {
      titulo.textContent = config.nombre;
      panel.setAttribute('aria-label', config.nombre);
    }
    if (config.politica) enlacePolitica.href = config.politica;
    if (config.maximo) entrada.maxLength = config.maximo;
    if (config.aviso && config.aviso.titulo) {
      banda.textContent = '';
      banda.appendChild(el('strong', '', 'Aviso: '));
      banda.appendChild(document.createTextNode(config.aviso.titulo));
      if (/^https?:\/\//.test(config.aviso.url || '')) banda.href = config.aviso.url;
      else banda.removeAttribute('href');
      banda.hidden = false;
    }
  }

  function abrir() {
    lanzador.hidden = true;
    panel.hidden = false;
    lanzador.setAttribute('aria-expanded', 'true');
    if (!iniciado) {
      iniciado = true;
      var cargando = el('div', 'msg bot');
      var puntosCarga = el('div', 'escribiendo');
      puntosCarga.append(el('i'), el('i'), el('i'));
      cargando.appendChild(puntosCarga);
      mensajes.appendChild(cargando);
      fetch(API + '/api/config')
        .then(function (r) { return r.json(); })
        .then(aplicarConfig)
        .catch(function () { /* el chat funciona sin la configuración */ })
        .finally(bienvenida);
    }
    entrada.focus();
  }

  function cerrar() {
    panel.hidden = true;
    lanzador.hidden = false;
    lanzador.setAttribute('aria-expanded', 'false');
    lanzador.focus();
  }

  function ajustarAltura() {
    entrada.style.height = 'auto';
    var alto = entrada.scrollHeight + 2;
    entrada.style.height = Math.min(alto, 96) + 'px';
    entrada.style.overflowY = alto > 96 ? 'auto' : 'hidden';
  }

  lanzador.addEventListener('click', abrir);
  botonCerrar.addEventListener('click', cerrar);
  botonReiniciar.addEventListener('click', function () {
    if (!PERFIL_FIJO) {
      perfil = null;
      guardado('asistente-perfil', null);
    }
    bienvenida();
  });
  panel.addEventListener('keydown', function (evento) {
    if (evento.key === 'Escape') cerrar();
  });
  entrada.addEventListener('input', ajustarAltura);
  entrada.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter' && !evento.shiftKey) {
      evento.preventDefault();
      preguntar(entrada.value);
    }
  });
  formulario.addEventListener('submit', function (evento) {
    evento.preventDefault();
    preguntar(entrada.value);
  });

  function montar() {
    document.body.appendChild(host);
  }
  if (document.body) montar();
  else document.addEventListener('DOMContentLoaded', montar);
})();
