/**
 * Panel de funcionarios del Asistente Univalle. Sin dependencias ni paso de compilación.
 * Todo el contenido se pinta con textContent: lo que se escribe en el panel nunca se interpreta como HTML.
 */
(function () {
  'use strict';

  const app = document.getElementById('app');
  const avisos = document.getElementById('avisos');
  const SVG = 'http://www.w3.org/2000/svg';
  const ESTADOS = { publicado: 'Publicado', revision: 'En revisión', borrador: 'Borrador', archivado: 'Archivado' };
  const ORIGENES = { manual: 'Escrito en el panel', semilla: 'Carga inicial', web: 'Página oficial' };
  const NOMBRE_TITULO = { faq: 'Pregunta', fecha: 'Nombre del evento', contacto: 'Oficina', articulo: 'Título', novedad: 'Título de la novedad', pagina: 'Título' };
  const NOMBRE_TEXTO = { faq: 'Respuesta aprobada', fecha: 'Descripción', contacto: 'Datos de contacto', articulo: 'Texto de la norma', novedad: 'Qué deben saber', pagina: 'Texto' };
  const NOMBRE_NUEVO = { faq: 'Nueva pregunta frecuente', novedad: 'Nueva novedad', fecha: 'Nueva fecha', contacto: 'Nuevo contacto' };
  const TIPOS_RESPUESTA = {
    aprobada: 'Respuesta aprobada', novedades: 'Novedades', ia: 'Redactada con IA', norma: 'Texto oficial literal',
    calendario: 'Remitida al calendario', personal: 'Dato personal', sin_informacion: 'Sin información',
    reintentar: 'IA sin respuesta', fuera_de_tema: 'Fuera de tema', saludo: 'Saludo', apoyo: 'Apoyo emocional',
  };

  let yo = null;
  let vistaActual = 'inicio';
  let filtros = { tipo: '', estado: '', dependencia: '', publico: '', origen: '', q: '', pagina: 1 };

  /** Crea un elemento. Los textos siempre se agregan como nodos de texto. */
  function h(etiqueta, atributos, ...hijos) {
    const nodo = document.createElement(etiqueta);
    for (const [clave, valor] of Object.entries(atributos || {})) {
      if (valor === undefined || valor === null || valor === false) continue;
      if (clave.startsWith('on')) nodo.addEventListener(clave.slice(2), valor);
      else if (clave === 'clase') nodo.className = valor;
      else if (clave === 'valor') nodo.value = valor;
      else if (valor === true) nodo.setAttribute(clave, '');
      else nodo.setAttribute(clave, valor);
    }
    for (const hijo of hijos.flat()) {
      if (hijo === null || hijo === undefined || hijo === false) continue;
      nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
    }
    return nodo;
  }

  function s(etiqueta, atributos, ...hijos) {
    const nodo = document.createElementNS(SVG, etiqueta);
    for (const [clave, valor] of Object.entries(atributos || {})) {
      if (valor !== undefined && valor !== null) nodo.setAttribute(clave, valor);
    }
    for (const hijo of hijos.flat()) {
      if (hijo !== null && hijo !== undefined) nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
    }
    return nodo;
  }

  /** Convierte **texto** en negrita sin interpretar HTML. */
  function conNegrita(texto) {
    return texto.split(/\*\*(.+?)\*\*/g).map((parte, i) => (i % 2 ? h('strong', null, parte) : parte));
  }

  function avisar(texto, mal) {
    const nodo = h('div', { clase: 'aviso' + (mal ? ' mal' : '') }, texto);
    avisos.append(nodo);
    setTimeout(() => nodo.remove(), mal ? 6000 : 3500);
  }

  async function api(ruta, opciones = {}) {
    const cabeceras = { 'X-Panel': '1', ...(opciones.cabeceras || {}) };
    const configuracion = { method: opciones.metodo || 'GET', headers: cabeceras, credentials: 'same-origin' };
    if (opciones.archivo) {
      configuracion.body = opciones.archivo;
    } else if (opciones.datos !== undefined) {
      cabeceras['Content-Type'] = 'application/json';
      configuracion.body = JSON.stringify(opciones.datos);
    }
    const respuesta = await fetch('/api/panel' + ruta, configuracion);
    const cuerpo = await respuesta.json().catch(() => ({}));
    if (respuesta.status === 401 && ruta !== '/entrar' && ruta !== '/yo') {
      yo = null;
      pintarEntrada('Tu sesión terminó. Vuelve a entrar.');
      throw new Error('Sesión terminada');
    }
    if (!respuesta.ok) throw new Error(typeof cuerpo.detail === 'string' ? cuerpo.detail : 'No se pudo completar la acción.');
    return cuerpo;
  }

  const post = (ruta, datos) => api(ruta, { metodo: 'POST', datos: datos === undefined ? {} : datos });
  const numero = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('es-CO'));

  function fechaCorta(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' });
  }

  function diaCorto(dia) {
    const [a, m, d] = dia.split('-').map(Number);
    return new Date(a, m - 1, d).toLocaleDateString('es-CO', { day: 'numeric', month: 'short' });
  }

  function etiquetaEstado(item) {
    const lista = [h('span', { clase: 'etiqueta ' + item.estado }, ESTADOS[item.estado])];
    if (item.pendiente_estado) {
      lista.push(h('span', { clase: 'etiqueta ' + item.pendiente_estado }, item.pendiente_estado === 'revision' ? 'Cambio en revisión' : 'Cambio en borrador'));
    }
    return lista;
  }

  function dialogo(contenido) {
    const nodo = h('dialog', { 'aria-label': 'Ventana' }, contenido);
    // Escape cierra la ventana de forma nativa; los botones la quitan de inmediato para no dejar formularios ocultos.
    nodo.addEventListener('close', () => nodo.remove());
    nodo.close = () => { HTMLDialogElement.prototype.close.call(nodo); nodo.remove(); };
    document.body.append(nodo);
    nodo.showModal();
    return nodo;
  }

  function claveTemporal(titulo, clave, explicacion) {
    const nodo = dialogo(h('div', { clase: 'editor' },
      h('div', { clase: 'editor-cabecera' }, h('h2', null, titulo), h('button', { clase: 'cerrar', type: 'button', 'aria-label': 'Cerrar', onclick: () => nodo.close() }, '×')),
      h('p', null, explicacion),
      h('p', { clase: 'clave-temporal' }, clave),
      h('p', { clase: 'nota info' }, 'Esta contraseña solo se muestra ahora. Entrégala por un canal seguro: la persona deberá cambiarla al entrar.'),
      h('div', { clase: 'acciones-editor' }, h('button', { clase: 'boton primario', type: 'button', onclick: () => nodo.close() }, 'Listo')),
    ));
  }

  // ---------- Entrada y contraseña ----------
  function pintarEntrada(mensaje) {
    const error = h('p', { clase: 'error', role: 'alert' }, mensaje || '');
    const correo = h('input', { type: 'email', required: true, autocomplete: 'username', name: 'correo' });
    const clave = h('input', { type: 'password', required: true, autocomplete: 'current-password', name: 'clave' });
    const boton = h('button', { clase: 'boton primario', type: 'submit' }, 'Entrar');
    const formulario = h('form', {
      onsubmit: async (evento) => {
        evento.preventDefault();
        boton.disabled = true;
        error.textContent = '';
        try {
          await post('/entrar', { correo: correo.value, clave: clave.value });
          await iniciar();
        } catch (fallo) {
          error.textContent = fallo.message;
          boton.disabled = false;
        }
      },
    },
      h('div', null, h('h1', null, 'Panel del asistente'), h('p', null, 'Administra lo que responde el asistente de la Universidad del Valle.')),
      h('label', { clase: 'campo' }, 'Correo', correo),
      h('label', { clase: 'campo' }, 'Contraseña', clave),
      error,
      boton,
    );
    app.replaceChildren(h('div', { clase: 'entrada' }, formulario));
    correo.focus();
  }

  function formularioClave(obligatorio, alTerminar) {
    const actual = h('input', { type: 'password', required: true, autocomplete: 'current-password' });
    const nueva = h('input', { type: 'password', required: true, autocomplete: 'new-password', minlength: 10 });
    const repetir = h('input', { type: 'password', required: true, autocomplete: 'new-password', minlength: 10 });
    const error = h('p', { clase: 'error', role: 'alert' });
    return h('form', {
      clase: 'apilado',
      onsubmit: async (evento) => {
        evento.preventDefault();
        error.textContent = '';
        if (nueva.value !== repetir.value) { error.textContent = 'Las contraseñas nuevas no coinciden.'; return; }
        try {
          await post('/mi-clave', { actual: actual.value, nueva: nueva.value });
          avisar('Contraseña actualizada.');
          alTerminar();
        } catch (fallo) {
          error.textContent = fallo.message;
        }
      },
    },
      obligatorio ? h('p', { clase: 'nota info' }, 'Entraste con una contraseña temporal. Crea una propia para continuar.') : null,
      h('label', { clase: 'campo' }, obligatorio ? 'Contraseña temporal' : 'Contraseña actual', actual),
      h('label', { clase: 'campo' }, 'Contraseña nueva', nueva, h('small', null, 'Mínimo 10 caracteres, con letras y números.')),
      h('label', { clase: 'campo' }, 'Repite la contraseña nueva', repetir),
      error,
      h('div', null, h('button', { clase: 'boton primario', type: 'submit' }, 'Guardar contraseña')),
    );
  }

  function pintarCambioObligatorio() {
    app.replaceChildren(h('div', { clase: 'entrada' }, h('div', { clase: 'tarjeta-entrada' },
      h('h1', null, 'Crea tu contraseña'),
      formularioClave(true, iniciar),
    )));
  }

  function abrirMiCuenta() {
    const nodo = dialogo(h('div', { clase: 'editor' },
      h('div', { clase: 'editor-cabecera' }, h('h2', null, 'Cambiar mi contraseña'), h('button', { clase: 'cerrar', type: 'button', 'aria-label': 'Cerrar', onclick: () => nodo.close() }, '×')),
      formularioClave(false, () => nodo.close()),
    ));
  }

  // ---------- Estructura ----------
  const VISTAS = [
    ['inicio', 'Inicio', vistaInicio],
    ['contenido', 'Contenido', vistaContenido],
    ['revision', 'Revisión', vistaRevision],
    ['fuentes', 'Páginas oficiales', vistaFuentes],
    ['sin', 'Por mejorar', vistaPorMejorar],
    ['importar', 'Importar documento', vistaImportar],
    ['probar', 'Probar el asistente', vistaProbar],
    ['actividad', 'Actividad', vistaActividad],
    ['usuarios', 'Usuarios', vistaUsuarios, 'admin'],
    ['ajustes', 'Ajustes', vistaAjustes],
  ];

  async function pintarEstructura() {
    const resumen = await api('/resumen');
    const contadores = { revision: resumen.en_revision, sin: resumen.sin_respuesta, fuentes: resumen.fuentes_con_error };
    const nav = h('nav', { 'aria-label': 'Secciones' },
      VISTAS.filter((v) => !v[3] || v[3] === yo.rol).map(([id, nombre]) => h('button', {
        type: 'button',
        'aria-current': id === vistaActual ? 'page' : null,
        onclick: () => ir(id),
      }, nombre, contadores[id] ? h('span', { clase: 'contador' }, contadores[id]) : null)),
    );
    const principal = h('main', { id: 'vista' });
    app.replaceChildren(h('div', { clase: 'estructura' },
      h('aside', { clase: 'lateral' },
        h('div', { clase: 'marca-panel' }, h('strong', null, 'Asistente Univalle'), h('span', null, 'Panel de administración')),
        nav,
        h('div', { clase: 'persona' },
          h('div', null, h('strong', null, yo.nombre), h('span', null, yo.nombre_rol + (yo.dependencia ? ' · ' + yo.dependencia : ''))),
          h('div', { clase: 'persona-acciones' },
            h('button', { type: 'button', onclick: abrirMiCuenta }, 'Mi contraseña'),
            h('button', { type: 'button', onclick: salir }, 'Salir'),
          ),
        ),
      ),
      principal,
    ));
    return principal;
  }

  async function ir(id) {
    vistaActual = id;
    try {
      const principal = await pintarEstructura();
      const vista = VISTAS.find((v) => v[0] === id)[2];
      await vista(principal);
    } catch (fallo) {
      if (yo) avisar(fallo.message, true);
    }
  }

  const refrescar = () => ir(vistaActual);

  async function salir() {
    await post('/salir');
    yo = null;
    pintarEntrada();
  }

  function titulo(texto, descripcion, accion) {
    return h('div', { clase: 'titulo-vista' }, h('div', null, h('h1', null, texto), descripcion ? h('p', null, descripcion) : null), accion);
  }

  // ---------- Inicio: tablero ----------
  function tarjetaCifra(etiqueta, valor, detalle, destino) {
    const contenido = [h('span', { clase: 'cifra-etiqueta' }, etiqueta), h('strong', { clase: 'cifra-valor' }, valor), detalle ? h('span', { clase: 'cifra-detalle' }, detalle) : null];
    return destino
      ? h('button', { clase: 'cifra', type: 'button', onclick: () => ir(destino) }, contenido)
      : h('div', { clase: 'cifra' }, contenido);
  }

  /** Columnas por día: una sola serie, sin leyenda (el título dice qué se mide), con detalle al pasar el cursor. */
  function graficoDias(dias) {
    const ancho = 640, alto = 210, izq = 34, der = 8, arriba = 14, abajo = 26;
    const maximo = Math.max(4, ...dias.map((d) => d.preguntas));
    const paso = Math.pow(10, Math.floor(Math.log10(maximo)));
    const tope = Math.ceil(maximo / paso) * paso;
    const marcas = [0, tope / 2, tope];
    const banda = (ancho - izq - der) / dias.length;
    const grosor = Math.min(24, banda - 6);
    const y = (v) => arriba + (alto - arriba - abajo) * (1 - v / tope);
    const consejo = h('div', { clase: 'consejo', role: 'status', hidden: true });
    const svg = s('svg', { viewBox: `0 0 ${ancho} ${alto}`, role: 'img', 'aria-label': `Preguntas por día. Máximo ${maximo}.`, clase: 'grafico' });
    svg.setAttribute('class', 'grafico');
    marcas.forEach((m) => {
      svg.append(s('line', { x1: izq, x2: ancho - der, y1: y(m), y2: y(m), class: 'rejilla' }));
      svg.append(s('text', { x: izq - 6, y: y(m) + 4, 'text-anchor': 'end', class: 'eje' }, numero(m)));
    });
    dias.forEach((d, i) => {
      const x = izq + i * banda + (banda - grosor) / 2;
      const base = y(0);
      const cima = y(d.preguntas);
      const largo = base - cima;
      const radio = Math.min(4, largo);
      const camino = largo > 0
        ? `M${x} ${base}V${cima + radio}Q${x} ${cima} ${x + radio} ${cima}H${x + grosor - radio}Q${x + grosor} ${cima} ${x + grosor} ${cima + radio}V${base}Z`
        : '';
      const grupo = s('g', { tabindex: 0, class: 'barra', 'aria-label': `${diaCorto(d.dia)}: ${d.preguntas} preguntas` });
      grupo.append(s('rect', { x: izq + i * banda, y: arriba, width: banda, height: alto - arriba - abajo, class: 'zona' }));
      if (camino) grupo.append(s('path', { d: camino, class: 'columna' }));
      const mostrar = () => {
        consejo.replaceChildren(h('strong', null, diaCorto(d.dia)), ` · ${numero(d.preguntas)} preguntas · ${numero(d.ia)} con IA · ${numero(d.sin_respuesta)} sin respuesta`);
        consejo.hidden = false;
      };
      grupo.addEventListener('mouseenter', mostrar);
      grupo.addEventListener('focus', mostrar);
      grupo.addEventListener('mouseleave', () => { consejo.hidden = true; });
      grupo.addEventListener('blur', () => { consejo.hidden = true; });
      svg.append(grupo);
      if (i === 0 || i === dias.length - 1 || i === Math.floor(dias.length / 2)) {
        svg.append(s('text', { x: izq + i * banda + banda / 2, y: alto - 8, 'text-anchor': 'middle', class: 'eje' }, diaCorto(d.dia)));
      }
    });
    const tabla = h('table', { clase: 'tabla-datos', hidden: true },
      h('thead', null, h('tr', null, h('th', null, 'Día'), h('th', null, 'Preguntas'), h('th', null, 'Con IA'), h('th', null, 'Sin respuesta'))),
      h('tbody', null, dias.map((d) => h('tr', null, h('td', null, diaCorto(d.dia)), h('td', null, numero(d.preguntas)), h('td', null, numero(d.ia)), h('td', null, numero(d.sin_respuesta))))),
    );
    const alternar = h('button', { clase: 'boton chico', type: 'button', onclick: () => { tabla.hidden = !tabla.hidden; alternar.textContent = tabla.hidden ? 'Ver tabla' : 'Ocultar tabla'; } }, 'Ver tabla');
    return h('div', { clase: 'tarjeta' },
      h('div', { clase: 'tarjeta-titulo' }, h('h2', null, 'Preguntas por día'), alternar),
      h('div', { clase: 'grafico-caja' }, svg, consejo),
      tabla,
    );
  }

  /** Cómo se respondió: barras horizontales ordenadas, una sola tinta, valor en la punta. */
  function graficoTipos(tipos) {
    const filas = Object.entries(tipos).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    if (!filas.length) return h('div', { clase: 'tarjeta' }, h('h2', null, 'Cómo se respondió'), h('p', { clase: 'vacio-chico' }, 'Aún no hay preguntas en este período.'));
    const maximo = filas[0][1];
    return h('div', { clase: 'tarjeta' },
      h('h2', null, 'Cómo se respondió'),
      h('div', { clase: 'barras' }, filas.map(([tipo, valor]) => h('div', { clase: 'barra-fila', title: `${TIPOS_RESPUESTA[tipo] || tipo}: ${valor}` },
        h('span', { clase: 'barra-nombre' }, TIPOS_RESPUESTA[tipo] || tipo),
        h('span', { clase: 'barra-pista' }, h('span', { clase: 'barra-relleno', style: null, 'data-ancho': Math.max(2, Math.round(100 * valor / maximo)) })),
        h('span', { clase: 'barra-valor' }, numero(valor)),
      ))),
    );
  }

  async function vistaInicio(destino) {
    const [r, e, ia] = await Promise.all([api('/resumen'), api('/estadisticas?dias=14'), api('/ia')]);
    const satisfaccion = e.valoraciones.porcentaje;
    destino.replaceChildren(
      titulo('Inicio', 'Lo que pasó con el asistente en los últimos 14 días.'),
      h('div', { clase: 'cifras' },
        h('div', { clase: 'cifra heroe' }, h('span', { clase: 'cifra-etiqueta' }, 'Preguntas respondidas'), h('strong', { clase: 'cifra-valor' }, numero(e.preguntas)), h('span', { clase: 'cifra-detalle' }, `${numero(r.preguntas_hoy)} hoy`)),
        tarjetaCifra('Resueltas sin usar IA', e.sin_ia === null ? '—' : `${e.sin_ia} %`, 'respuestas aprobadas, novedades y textos oficiales'),
        tarjetaCifra('Les sirvió', satisfaccion === null ? '—' : `${satisfaccion} %`, `${numero(e.valoraciones.total)} valoraciones`, 'sin'),
        tarjetaCifra('Por mejorar', numero(r.sin_respuesta), 'preguntas sin respuesta', 'sin'),
        tarjetaCifra('Esperan revisión', numero(r.en_revision), null, 'revision'),
      ),
      h('div', { clase: 'rejilla-tablero' }, graficoDias(e.dias), graficoTipos(e.tipos)),
      h('div', { clase: 'tarjeta estado-ia' },
        h('span', { clase: 'punto' + (r.ia ? '' : ' apagado') }),
        h('div', null,
          h('h2', null, r.ia ? 'Redacción con IA activa' : r.ia_configurada ? 'IA pausada en Ajustes' : 'Modo sin IA'),
          h('p', null, r.ia
            ? `Proveedores, en orden: ${ia.proveedores.map((p) => `${p.nombre} (${p.modelo})`).join(', ')}. Hoy: ${r.llamadas_ia_hoy} de ${r.tope_ia} llamadas; al llegar al tope sigue respondiendo sin IA.`
            : 'El asistente responde con las preguntas aprobadas, las páginas oficiales y el texto literal de las normas. Para que redacte en lenguaje sencillo, agrega una clave gratuita de Gemini, Groq o Cohere.'),
          h('p', null, ia.busqueda.nombre === 'ninguna'
            ? 'Búsqueda por significado: desactivada (se busca por palabras clave).'
            : `Búsqueda por significado: ${ia.busqueda.nombre === 'local' ? 'modelo local gratuito, sin límites' : ia.busqueda.nombre}.`),
        ),
      ),
    );
    destino.querySelectorAll('.barra-relleno').forEach((barra) => { barra.style.width = barra.dataset.ancho + '%'; });
  }

  // ---------- Contenido ----------
  function filaContenido(item) {
    const vista = item.vista;
    const meta = [item.dependencia];
    if (item.fuente) meta.push(item.fuente);
    if (item.publico && item.publico !== 'todos') meta.push('Para ' + yo.publicos[item.publico].toLowerCase());
    if (item.fecha_legible) meta.push(item.fecha_legible);
    if (item.origen === 'web') meta.push('Se actualiza sola');
    return h('button', { clase: 'item', type: 'button', onclick: () => abrirEditor(item.id) },
      h('strong', null, vista.titulo),
      h('span', { clase: 'etiquetas' }, h('span', { clase: 'etiqueta tipo' }, yo.tipos[item.tipo]), item.destacada && item.tipo === 'novedad' ? h('span', { clase: 'etiqueta aviso-chat' }, 'Aviso en el chat') : null, etiquetaEstado(item)),
      h('span', { clase: 'detalle' }, vista.texto.replace(/\*\*/g, '')),
      h('span', { clase: 'meta' }, meta.map((m) => h('span', null, m))),
    );
  }

  async function vistaContenido(destino) {
    const contenedor = h('div');
    const cargar = async () => {
      const parametros = new URLSearchParams(Object.entries(filtros).filter(([, v]) => v));
      const datos = await api('/contenidos?' + parametros);
      const paginas = Math.max(1, Math.ceil(datos.total / datos.por_pagina));
      contenedor.replaceChildren(
        datos.items.length
          ? h('div', { clase: 'lista' }, datos.items.map(filaContenido))
          : h('div', { clase: 'lista' }, h('div', { clase: 'vacio' }, 'No hay contenido con esos filtros.')),
        h('div', { clase: 'paginas' },
          h('span', null, `${numero(datos.total)} resultados`),
          h('div', null,
            h('button', { clase: 'boton chico', type: 'button', disabled: filtros.pagina <= 1, onclick: () => { filtros.pagina -= 1; cargar(); } }, 'Anterior'),
            h('span', null, ` Página ${filtros.pagina} de ${paginas} `),
            h('button', { clase: 'boton chico', type: 'button', disabled: filtros.pagina >= paginas, onclick: () => { filtros.pagina += 1; cargar(); } }, 'Siguiente'),
          ),
        ),
      );
    };
    const cambio = (clave) => (evento) => { filtros[clave] = evento.target.value; filtros.pagina = 1; cargar(); };
    const selector = (clave, etiqueta, opciones) => h('select', { 'aria-label': etiqueta, onchange: cambio(clave) },
      h('option', { value: '' }, etiqueta),
      Object.entries(opciones).map(([valor, nombre]) => h('option', { value: valor, selected: filtros[clave] === valor }, nombre)),
    );
    let espera = null;
    destino.replaceChildren(
      titulo('Contenido', 'Todo lo que el asistente puede responder.',
        h('div', { clase: 'etiquetas' },
          Object.entries(NOMBRE_NUEVO).map(([tipo, nombre], i) =>
            h('button', { clase: 'boton' + (i < 2 ? ' primario' : ''), type: 'button', onclick: () => abrirNuevo(tipo) }, nombre)),
        ),
      ),
      h('div', { clase: 'filtros' },
        h('input', {
          type: 'search', placeholder: 'Buscar en títulos y textos', 'aria-label': 'Buscar', valor: filtros.q,
          oninput: (evento) => {
            clearTimeout(espera);
            espera = setTimeout(() => { filtros.q = evento.target.value; filtros.pagina = 1; cargar(); }, 250);
          },
        }),
        selector('tipo', 'Todos los tipos', yo.tipos),
        selector('estado', 'Todos los estados', ESTADOS),
        selector('publico', 'Todo público', yo.publicos),
        selector('origen', 'Cualquier origen', ORIGENES),
        selector('dependencia', 'Todas las dependencias', Object.fromEntries(yo.dependencias.map((d) => [d, d]))),
      ),
      contenedor,
    );
    await cargar();
  }

  // ---------- Editor ----------
  function camposEditor(tipo, datos, soloLectura) {
    const entrada = (atributos) => h('input', { ...atributos, disabled: soloLectura });
    const campos = {
      titulo: entrada({ type: 'text', valor: datos.titulo || '', required: true, maxlength: 300 }),
      texto: h('textarea', { required: true, maxlength: 40000, disabled: soloLectura }, datos.texto || ''),
      url: entrada({ type: 'url', valor: datos.url || '', placeholder: 'https://' }),
      inicio: entrada({ type: 'date', valor: datos.inicio || '' }),
      fin: entrada({ type: 'date', valor: datos.fin || '', required: tipo === 'fecha' }),
      capitulo: entrada({ type: 'text', valor: datos.capitulo || '' }),
      destacada: h('input', { type: 'checkbox', checked: !!datos.destacada, disabled: soloLectura }),
      publico: h('select', { disabled: soloLectura }, Object.entries(yo.publicos).map(([valor, nombre]) => h('option', { value: valor, selected: (datos.publico || 'todos') === valor }, nombre))),
    };
    const nodos = [
      h('label', { clase: 'campo' }, NOMBRE_TITULO[tipo], campos.titulo),
      h('label', { clase: 'campo' }, NOMBRE_TEXTO[tipo], campos.texto,
        ['faq', 'novedad'].includes(tipo) ? h('small', null, 'Se muestra tal cual. Usa **negrita**, y líneas con «- » o «1. » para hacer listas.') : null),
    ];
    if (tipo === 'fecha' || tipo === 'novedad') {
      nodos.push(h('div', { clase: 'fila' },
        h('label', { clase: 'campo' }, tipo === 'novedad' ? 'Publicar desde (opcional)' : 'Desde (opcional)', campos.inicio),
        h('label', { clase: 'campo' }, tipo === 'novedad' ? 'Mostrar hasta (opcional)' : 'Hasta', campos.fin, h('small', null, 'Después de este día deja de mostrarse sola.')),
      ));
    }
    if (tipo === 'articulo') nodos.push(h('label', { clase: 'campo' }, 'Capítulo', campos.capitulo));
    nodos.push(h('div', { clase: 'fila' },
      h('label', { clase: 'campo' }, 'Enlace oficial', campos.url),
      h('label', { clase: 'campo' }, 'Para quién es', campos.publico),
    ));
    if (tipo === 'novedad') nodos.push(h('label', { clase: 'marca' }, campos.destacada, 'Mostrar como aviso destacado en la parte superior del chat'));
    const leer = () => ({
      titulo: campos.titulo.value,
      texto: campos.texto.value,
      url: campos.url.value,
      inicio: campos.inicio.value,
      fin: campos.fin.value,
      capitulo: campos.capitulo.value,
      destacada: campos.destacada.checked,
      publico: campos.publico.value,
    });
    return { nodos, leer };
  }

  function abrirNuevo(tipo, base) {
    const propias = yo.rol === 'admin' ? yo.dependencias : [yo.dependencia];
    const dependencia = h('select', null, propias.map((d) => h('option', { value: d }, d)));
    const { nodos, leer } = camposEditor(tipo, base || {}, false);
    const error = h('p', { clase: 'error', role: 'alert' });
    const nodo = dialogo(h('form', {
      clase: 'editor',
      onsubmit: async (evento) => {
        evento.preventDefault();
        try {
          const { id } = await post('/contenidos', { ...leer(), tipo, dependencia: dependencia.value });
          nodo.close();
          avisar('Guardado como borrador.');
          abrirEditor(id);
        } catch (fallo) {
          error.textContent = fallo.message;
        }
      },
    },
      h('div', { clase: 'editor-cabecera' },
        h('h2', null, NOMBRE_NUEVO[tipo]),
        h('button', { clase: 'cerrar', type: 'button', 'aria-label': 'Cerrar', onclick: () => nodo.close() }, '×'),
      ),
      h('label', { clase: 'campo' }, 'Dependencia responsable', dependencia),
      nodos,
      error,
      h('div', { clase: 'acciones-editor' }, h('button', { clase: 'boton primario', type: 'submit' }, 'Guardar borrador')),
    ));
  }

  async function abrirEditor(id) {
    let datos;
    try {
      datos = await api('/contenidos/' + id);
    } catch (fallo) {
      avisar(fallo.message, true);
      return;
    }
    const deLaWeb = datos.origen === 'web';
    const soloLectura = !datos.puede_editar || datos.estado === 'archivado' || deLaWeb;
    const { nodos, leer } = camposEditor(datos.tipo, datos.vista, soloLectura);
    const error = h('p', { clase: 'error', role: 'alert' });
    const enRevision = datos.estado === 'revision' || datos.pendiente_estado === 'revision';
    const hayPendiente = datos.tiene_cambios || datos.estado === 'borrador' || datos.estado === 'revision';

    const accion = (ruta, mensaje, cuerpo) => async () => {
      try {
        await post(`/contenidos/${id}/${ruta}`, cuerpo);
        nodo.close();
        avisar(mensaje);
        await refrescar();
        if (ruta !== 'archivar') abrirEditor(id);
      } catch (fallo) {
        error.textContent = fallo.message;
      }
    };

    const guardar = async (evento) => {
      evento.preventDefault();
      try {
        await post('/contenidos/' + id, leer());
        nodo.close();
        avisar('Cambios guardados. El público aún no los ve.');
        await refrescar();
        abrirEditor(id);
      } catch (fallo) {
        error.textContent = fallo.message;
      }
    };

    const devolver = () => {
      const nota = window.prompt('¿Qué hay que corregir?');
      if (nota !== null) accion('devolver', 'Devuelto al editor.', { nota })();
    };

    const avisosEditor = [];
    if (deLaWeb) avisosEditor.push(h('p', { clase: 'nota info' }, `Viene de la página oficial «${datos.fuente || 'sin nombre'}» y se actualiza sola cuando la página cambia. Para corregirla, hay que corregir la página. Si no debe usarse, retírala.`));
    if (datos.nota_revision) avisosEditor.push(h('p', { clase: 'nota' }, 'Devuelto por el aprobador: ' + datos.nota_revision));
    if (datos.reemplazado_por) avisosEditor.push(h('p', { clase: 'nota' }, 'Esta versión fue reemplazada por una norma posterior.'));
    if (!datos.puede_editar) avisosEditor.push(h('p', { clase: 'nota info' }, `Este contenido es de ${datos.dependencia}. Puedes verlo, pero no cambiarlo.`));
    if (datos.fuente_nota) avisosEditor.push(h('p', { clase: 'nota info' }, datos.fuente_nota));

    // El aprobador debe ver lo que cambia, sea el texto, la fecha, el público o el enlace.
    const version = (v) => [
      v.titulo,
      v.fin ? 'Fecha: ' + [v.inicio, v.fin].filter(Boolean).filter((f, i, l) => l.indexOf(f) === i).join(' a ') : '',
      v.publico && v.publico !== 'todos' ? 'Para: ' + yo.publicos[v.publico] : '',
      v.texto,
      v.url ? 'Enlace: ' + v.url : '',
    ].filter(Boolean).join('\n\n');
    const comparacion = datos.tiene_cambios && datos.publicado
      ? h('div', { clase: 'comparacion' },
        h('div', null, h('h3', null, 'Publicado ahora'), version(datos.publicado)),
        h('div', null, h('h3', null, 'Cambio pendiente'), version(datos.vista)))
      : null;

    const botones = [];
    if (datos.puede_publicar && datos.estado === 'publicado') {
      botones.push(h('button', { clase: 'boton peligro separar', type: 'button', onclick: accion('archivar', 'Retirado del asistente.') }, 'Retirar del asistente'));
    }
    if (datos.puede_editar && datos.tiene_cambios) {
      botones.push(h('button', { clase: 'boton', type: 'button', onclick: accion('descartar', 'Cambios descartados.') }, 'Descartar cambios'));
    }
    if (!soloLectura) botones.push(h('button', { clase: 'boton', type: 'submit' }, 'Guardar cambios'));
    if (datos.puede_editar && hayPendiente && !enRevision && !deLaWeb) {
      botones.push(h('button', { clase: 'boton primario', type: 'button', onclick: accion('enviar', 'Enviado a revisión.') }, 'Enviar a revisión'));
    }
    if (datos.puede_publicar && enRevision) {
      botones.push(h('button', { clase: 'boton', type: 'button', onclick: devolver }, 'Devolver'));
    }
    if (datos.puede_publicar && hayPendiente && !deLaWeb) {
      botones.push(h('button', { clase: 'boton primario', type: 'button', onclick: accion('publicar', 'Publicado. El asistente ya lo usa.') }, 'Publicar'));
    }

    const nodo = dialogo(h('form', { clase: 'editor', onsubmit: guardar },
      h('div', { clase: 'editor-cabecera' },
        h('div', null,
          h('h2', null, datos.vista.titulo),
          h('div', { clase: 'etiquetas' }, h('span', { clase: 'etiqueta tipo' }, yo.tipos[datos.tipo]), h('span', { clase: 'etiqueta tipo' }, datos.dependencia), etiquetaEstado(datos)),
        ),
        h('button', { clase: 'cerrar', type: 'button', 'aria-label': 'Cerrar', onclick: () => nodo.close() }, '×'),
      ),
      avisosEditor,
      comparacion,
      nodos,
      error,
      h('div', { clase: 'acciones-editor' }, botones),
      h('details', null,
        h('summary', null, `Historial (${datos.versiones.length})`),
        h('div', { clase: 'versiones' }, datos.versiones.map((version, indice) => h('div', { clase: 'renglon' },
          h('div', null, h('div', null, version.accion), h('div', { clase: 'meta' }, `${version.autor} · ${fechaCorta(version.fecha)}`)),
          datos.puede_editar && !deLaWeb && indice > 0
            ? h('button', { clase: 'boton chico', type: 'button', onclick: accion('restaurar/' + version.id, 'Versión recuperada como cambio pendiente.') }, 'Restaurar')
            : null,
        ))),
      ),
    ));
  }

  // ---------- Revisión ----------
  async function vistaRevision(destino) {
    const datos = await api('/contenidos?estado=revision');
    destino.replaceChildren(
      titulo('Revisión', yo.puede_publicar ? 'Cambios que esperan tu aprobación.' : 'Cambios enviados, a la espera de un aprobador.'),
      datos.items.length
        ? h('div', { clase: 'lista' }, datos.items.map(filaContenido))
        : h('div', { clase: 'lista' }, h('div', { clase: 'vacio' }, 'No hay nada pendiente de revisión.')),
    );
  }

  // ---------- Páginas oficiales ----------
  async function vistaFuentes(destino) {
    const fuentes = await api('/fuentes-web');
    const propias = yo.rol === 'admin' ? yo.dependencias : [yo.dependencia];
    const nombre = h('input', { type: 'text', required: true, minlength: 3, maxlength: 120, placeholder: 'Ej.: Becas y estímulos' });
    const url = h('input', { type: 'url', required: true, placeholder: 'https://…univalle.edu.co/…' });
    const tipo = h('select', null, h('option', { value: 'pagina' }, 'Página'), h('option', { value: 'noticias' }, 'Canal de noticias (RSS)'));
    const dependencia = h('select', null, propias.map((d) => h('option', { value: d }, d)));
    const publico = h('select', null, Object.entries(yo.publicos).map(([v, n]) => h('option', { value: v }, n)));
    const error = h('p', { clase: 'error', role: 'alert' });
    const boton = h('button', { clase: 'boton primario', type: 'submit' }, 'Agregar y leer ahora');
    const estado = (f) => {
      if (!f.activa) return h('span', { clase: 'etiqueta archivado' }, 'Pausada');
      if (f.error) return h('span', { clase: 'etiqueta error-etiqueta' }, 'Con error');
      if (!f.ultima_revision) return h('span', { clase: 'etiqueta borrador' }, 'Pendiente');
      return h('span', { clase: 'etiqueta publicado' }, 'Al día');
    };
    const puedeCambiar = (f) => yo.rol === 'admin' || (yo.rol === 'aprobador' && yo.dependencia === f.dependencia);
    const actualizar = (f) => async (evento) => {
      evento.target.disabled = true;
      evento.target.textContent = 'Leyendo…';
      try {
        const r = await post(`/fuentes-web/${f.id}/actualizar`);
        avisar(r.error ? r.error : r.sin_cambios ? 'Sin cambios desde la última lectura.' : `Listo: ${r.nuevas} nuevas, ${r.actualizadas} actualizadas, ${r.retiradas} retiradas.`, !!r.error);
      } catch (fallo) {
        avisar(fallo.message, true);
      }
      refrescar();
    };
    destino.replaceChildren(
      titulo('Páginas oficiales', 'El asistente las vuelve a leer solo cada pocas horas. Si una página cambia, lo que responde cambia con ella y queda en el historial.'),
      h('div', { clase: 'lista' }, fuentes.map((f) => h('div', { clase: 'renglon' },
        h('div', null,
          h('div', { clase: 'renglon-titulo' }, h('strong', null, f.nombre), ' ', estado(f), ' ', h('span', { clase: 'etiqueta tipo' }, f.tipo === 'noticias' ? 'Noticias' : 'Página')),
          h('div', { clase: 'meta' }, h('a', { href: f.url, target: '_blank', rel: 'noopener' }, f.url)),
          h('div', { clase: 'meta' }, [
            f.dependencia,
            yo.publicos[f.publico] ? 'Para ' + yo.publicos[f.publico].toLowerCase() : '',
            f.piezas ? `${f.piezas} ${f.piezas === 1 ? 'pieza' : 'piezas'}` : '',
            f.ultima_revision ? 'Leída ' + fechaCorta(f.ultima_revision) : 'Aún no se ha leído',
            f.ultimo_cambio ? 'Último cambio ' + fechaCorta(f.ultimo_cambio) : '',
          ].filter(Boolean).join(' · ')),
          f.error ? h('div', { clase: 'error' }, f.error) : null,
        ),
        h('div', { clase: 'acciones' },
          f.activa ? h('button', { clase: 'boton chico', type: 'button', onclick: actualizar(f) }, 'Leer ahora') : null,
          puedeCambiar(f) && h('button', { clase: 'boton chico', type: 'button', onclick: async () => {
            try { await post(`/fuentes-web/${f.id}/activa`, { activa: !f.activa }); avisar(f.activa ? 'Fuente pausada: ya no se usa.' : 'Fuente activada: se leerá en la próxima revisión.'); } catch (fallo) { avisar(fallo.message, true); }
            refrescar();
          } }, f.activa ? 'Pausar' : 'Activar'),
        ),
      ))),
      yo.puede_publicar ? h('form', {
        clase: 'tarjeta apilado separado',
        onsubmit: async (evento) => {
          evento.preventDefault();
          error.textContent = '';
          boton.disabled = true;
          try {
            const r = await post('/fuentes-web', { nombre: nombre.value, url: url.value, tipo: tipo.value, dependencia: dependencia.value, publico: publico.value });
            avisar(r.error ? 'Se agregó, pero no se pudo leer: ' + r.error : `Agregada: ${r.nuevas} piezas nuevas.`, !!r.error);
            refrescar();
          } catch (fallo) {
            error.textContent = fallo.message;
            boton.disabled = false;
          }
        },
      },
        h('h2', null, 'Agregar una página oficial'),
        h('p', { clase: 'suave' }, 'Solo se aceptan direcciones https de univalle.edu.co. Lo que publique esa página empieza a responderse de inmediato.'),
        h('div', { clase: 'fila' }, h('label', { clase: 'campo' }, 'Nombre', nombre), h('label', { clase: 'campo' }, 'Tipo', tipo)),
        h('label', { clase: 'campo' }, 'Dirección', url),
        h('div', { clase: 'fila' }, h('label', { clase: 'campo' }, 'Dependencia', dependencia), h('label', { clase: 'campo' }, 'Para quién es', publico)),
        error,
        h('div', null, boton),
      ) : null,
    );
  }

  // ---------- Por mejorar ----------
  async function vistaPorMejorar(destino) {
    const [filas, e] = await Promise.all([api('/sin-respuesta'), api('/estadisticas?dias=30')]);
    destino.replaceChildren(
      titulo('Por mejorar', 'Lo que la gente preguntó y no encontró, y las respuestas que alguien marcó como inútiles. Se guardan sin correos, nombres ni números de documento.'),
      h('h2', { clase: 'subtitulo' }, 'Preguntas sin respuesta'),
      filas.length
        ? h('div', { clase: 'lista' }, filas.map((fila) => h('div', { clase: 'renglon' },
          h('div', null, h('div', null, fila.pregunta), h('div', { clase: 'meta' }, `${fila.veces} ${fila.veces === 1 ? 'vez' : 'veces'} · última: ${fechaCorta(fila.ultima)}`)),
          h('div', { clase: 'acciones' },
            h('button', { clase: 'boton chico primario', type: 'button', onclick: () => abrirNuevo('faq', { titulo: fila.pregunta }) }, 'Crear respuesta'),
            h('button', {
              clase: 'boton chico', type: 'button',
              onclick: async () => { await post(`/sin-respuesta/${fila.id}/resolver`); refrescar(); },
            }, 'Marcar atendida'),
          ),
        )))
        : h('div', { clase: 'lista' }, h('div', { clase: 'vacio' }, 'Por ahora el asistente ha podido responder todo.')),
      h('h2', { clase: 'subtitulo' }, 'Respuestas que no sirvieron'),
      e.mal_valoradas.length
        ? h('div', { clase: 'lista' }, e.mal_valoradas.map((m) => h('div', { clase: 'renglon' },
          h('div', null, h('div', null, m.pregunta), h('div', { clase: 'meta' }, `${TIPOS_RESPUESTA[m.tipo] || m.tipo} · ${m.fuentes.join(' · ') || 'sin fuente'} · ${fechaCorta(m.fecha)}`)),
          h('div', { clase: 'acciones' }, h('button', { clase: 'boton chico', type: 'button', onclick: () => abrirNuevo('faq', { titulo: m.pregunta }) }, 'Crear respuesta')),
        )))
        : h('div', { clase: 'lista' }, h('div', { clase: 'vacio' }, 'Nadie ha marcado una respuesta como inútil.')),
    );
  }

  // ---------- Importar ----------
  function vistaImportar(destino) {
    const resultado = h('div', { clase: 'apilado' });
    const archivo = h('input', { type: 'file', accept: '.pdf,.docx,.txt', required: true });
    const pegado = h('textarea', { placeholder: 'ARTÍCULO 1. …' });

    const mostrar = (datos) => {
      const propias = yo.rol === 'admin' ? yo.dependencias : [yo.dependencia];
      const nombre = h('input', { type: 'text', required: true, placeholder: 'Ej.: Acuerdo 010 de 2026', minlength: 3 });
      const dependencia = h('select', null, propias.map((d) => h('option', { value: d }, d)));
      const url = h('input', { type: 'url', placeholder: 'https://' });
      const publico = h('select', null, Object.entries(yo.publicos).map(([v, n]) => h('option', { value: v }, n)));
      const error = h('p', { clase: 'error', role: 'alert' });
      const piezas = [];
      datos.advertencias.forEach((texto) => piezas.push(h('p', { clase: datos.es_escaneo ? 'nota error-caja' : 'nota' }, texto)));
      if (datos.segmentos.length) {
        piezas.push(h('form', {
          clase: 'tarjeta apilado',
          onsubmit: async (evento) => {
            evento.preventDefault();
            try {
              const r = await post('/importar/confirmar', { nombre: nombre.value, dependencia: dependencia.value, url: url.value, publico: publico.value, segmentos: datos.segmentos });
              avisar(`Se crearon ${r.creados} borradores.`);
              filtros = { tipo: 'articulo', estado: 'borrador', dependencia: '', publico: '', origen: '', q: '', pagina: 1 };
              ir('contenido');
            } catch (fallo) {
              error.textContent = fallo.message;
            }
          },
        },
          h('h2', null, `Se encontraron ${datos.segmentos.length} piezas`),
          h('p', null, 'Revísalas. Quedarán como borradores: nada llega al público hasta que se apruebe.'),
          h('div', { clase: 'fila' },
            h('label', { clase: 'campo' }, 'Nombre de la norma', nombre),
            h('label', { clase: 'campo' }, 'Dependencia', dependencia),
          ),
          h('div', { clase: 'fila' }, h('label', { clase: 'campo' }, 'Enlace oficial', url), h('label', { clase: 'campo' }, 'Para quién es', publico)),
          h('div', { clase: 'segmentos' }, datos.segmentos.map((s2) => h('div', { clase: 'segmento' }, h('strong', null, s2.titulo), h('p', null, s2.texto)))),
          error,
          h('div', { clase: 'acciones-editor' }, h('button', { clase: 'boton primario', type: 'submit' }, 'Crear borradores')),
        ));
      }
      resultado.replaceChildren(...piezas);
    };

    const enviar = async (nombreArchivo, contenido) => {
      const cuerpo = new FormData();
      cuerpo.append('archivo', contenido, nombreArchivo);
      resultado.replaceChildren(h('p', null, 'Leyendo el documento…'));
      try {
        mostrar(await api('/importar', { metodo: 'POST', archivo: cuerpo }));
      } catch (fallo) {
        resultado.replaceChildren(h('p', { clase: 'nota error-caja' }, fallo.message));
      }
    };

    destino.replaceChildren(
      titulo('Importar documento', 'Sube una norma y el sistema la separa por artículos, corrige acentos dañados y avisa si es un escaneo.'),
      h('div', { clase: 'tarjeta apilado' },
        h('form', { clase: 'apilado', onsubmit: (e) => { e.preventDefault(); enviar(archivo.files[0].name, archivo.files[0]); } },
          h('label', { clase: 'campo' }, 'Archivo PDF, Word (.docx) o texto', archivo),
          h('div', null, h('button', { clase: 'boton primario', type: 'submit' }, 'Analizar archivo')),
        ),
        h('details', null,
          h('summary', null, '¿Es un escaneo? Pega aquí el texto'),
          h('form', { clase: 'apilado', onsubmit: (e) => { e.preventDefault(); if (pegado.value.trim()) enviar('pegado.txt', new Blob([pegado.value], { type: 'text/plain' })); } },
            h('label', { clase: 'campo' }, 'Texto del documento', pegado),
            h('div', null, h('button', { clase: 'boton', type: 'submit' }, 'Analizar texto')),
          ),
        ),
      ),
      resultado,
    );
  }

  // ---------- Probar ----------
  function vistaProbar(destino) {
    const mensajes = h('div', { clase: 'prueba-mensajes', role: 'log', 'aria-live': 'polite' },
      h('div', { clase: 'burbuja bot' }, 'Este chat ya usa los borradores y cambios en revisión. Solo lo ves tú: no afecta al público ni a las estadísticas.'));
    const entrada = h('input', { type: 'text', placeholder: 'Escribe una pregunta de prueba', 'aria-label': 'Pregunta de prueba', maxlength: 500 });
    const perfil = h('select', { 'aria-label': 'Perfil de quien pregunta' }, h('option', { value: '' }, 'Sin perfil'), h('option', { value: 'aspirante' }, 'Aspirante'), h('option', { value: 'estudiante' }, 'Estudiante'));
    const boton = h('button', { clase: 'boton primario', type: 'submit' }, 'Preguntar');
    const historial = [];
    destino.replaceChildren(
      titulo('Probar el asistente', 'Comprueba cómo quedará una respuesta antes de publicarla.'),
      h('div', { clase: 'tarjeta prueba' },
        mensajes,
        h('form', {
          onsubmit: async (evento) => {
            evento.preventDefault();
            const pregunta = entrada.value.trim();
            if (pregunta.length < 2) return;
            mensajes.append(h('div', { clase: 'burbuja yo' }, pregunta));
            entrada.value = '';
            boton.disabled = true;
            try {
              const r = await post('/probar', { pregunta, historial: historial.slice(-6), perfil: perfil.value || null });
              const fuentes = r.fuentes.map((f) => f.titulo + (f.borrador ? ' (sin publicar)' : '')).join(' · ');
              mensajes.append(h('div', { clase: 'burbuja bot' }, conNegrita(r.respuesta), h('small', null, [TIPOS_RESPUESTA[r.tipo] || r.tipo, fuentes].filter(Boolean).join(' — '))));
              historial.push({ rol: 'usuario', texto: pregunta }, { rol: 'asistente', texto: r.respuesta.slice(0, 600) });
            } catch (fallo) {
              avisar(fallo.message, true);
            }
            boton.disabled = false;
            mensajes.scrollTop = mensajes.scrollHeight;
            entrada.focus();
          },
        }, perfil, entrada, boton),
      ),
    );
    entrada.focus();
  }

  // ---------- Actividad ----------
  async function vistaActividad(destino) {
    const filas = await api('/actividad');
    destino.replaceChildren(
      titulo('Actividad', 'Quién cambió qué y cuándo, incluidas las actualizaciones automáticas desde las páginas oficiales.'),
      filas.length
        ? h('div', { clase: 'lista' }, filas.map((fila) => h('button', { clase: 'item', type: 'button', onclick: () => abrirEditor(fila.contenido_id) },
          h('strong', null, fila.titulo),
          h('span', { clase: 'etiquetas' }, h('span', { clase: 'etiqueta tipo' }, fila.accion.split(':')[0])),
          h('span', { clase: 'meta' }, h('span', null, fila.autor), h('span', null, fila.dependencia), h('span', null, fechaCorta(fila.fecha))),
        )))
        : h('div', { clase: 'lista' }, h('div', { clase: 'vacio' }, 'Todavía no hay cambios registrados.')),
    );
  }

  // ---------- Usuarios ----------
  async function vistaUsuarios(destino) {
    const lista = await api('/usuarios');
    const correo = h('input', { type: 'email', required: true, placeholder: 'persona@correounivalle.edu.co' });
    const nombre = h('input', { type: 'text', required: true, minlength: 3, maxlength: 80 });
    const rol = h('select', null, Object.entries(yo.roles).map(([v, n]) => h('option', { value: v, selected: v === 'editor' }, n)));
    const dependencia = h('select', null, yo.dependencias.map((d) => h('option', { value: d }, d)));
    const error = h('p', { clase: 'error', role: 'alert' });
    const editarUsuario = (u) => {
      const rolE = h('select', null, Object.entries(yo.roles).map(([v, n]) => h('option', { value: v, selected: v === u.rol }, n)));
      const depE = h('select', null, yo.dependencias.map((d) => h('option', { value: d, selected: d === u.dependencia }, d)));
      const activo = h('input', { type: 'checkbox', checked: !!u.activo });
      const err = h('p', { clase: 'error', role: 'alert' });
      const nodo = dialogo(h('form', {
        clase: 'editor',
        onsubmit: async (evento) => {
          evento.preventDefault();
          try {
            await post(`/usuarios/${u.id}`, { rol: rolE.value, dependencia: depE.value, activo: activo.checked });
            nodo.close();
            avisar('Usuario actualizado.');
            refrescar();
          } catch (fallo) { err.textContent = fallo.message; }
        },
      },
        h('div', { clase: 'editor-cabecera' }, h('div', null, h('h2', null, u.nombre), h('p', { clase: 'suave' }, u.correo)), h('button', { clase: 'cerrar', type: 'button', 'aria-label': 'Cerrar', onclick: () => nodo.close() }, '×')),
        h('div', { clase: 'fila' }, h('label', { clase: 'campo' }, 'Rol', rolE), h('label', { clase: 'campo' }, 'Dependencia', depE)),
        h('label', { clase: 'marca' }, activo, 'Cuenta activa'),
        err,
        h('div', { clase: 'acciones-editor' },
          h('button', { clase: 'boton separar', type: 'button', onclick: async () => {
            try { const r = await post(`/usuarios/${u.id}/clave`); nodo.close(); claveTemporal('Contraseña restablecida', r.clave_temporal, `Nueva contraseña temporal para ${u.correo}:`); } catch (fallo) { err.textContent = fallo.message; }
          } }, 'Restablecer contraseña'),
          h('button', { clase: 'boton primario', type: 'submit' }, 'Guardar'),
        ),
      ));
    };
    destino.replaceChildren(
      titulo('Usuarios', 'Quién puede editar y aprobar el contenido de cada dependencia.'),
      h('div', { clase: 'lista' }, lista.map((u) => h('button', { clase: 'item', type: 'button', onclick: () => editarUsuario(u) },
        h('strong', null, u.nombre),
        h('span', { clase: 'etiquetas' }, h('span', { clase: 'etiqueta tipo' }, yo.roles[u.rol]), u.activo ? null : h('span', { clase: 'etiqueta archivado' }, 'Inactiva'), u.debe_cambiar_clave ? h('span', { clase: 'etiqueta borrador' }, 'Clave temporal') : null),
        h('span', { clase: 'meta' }, h('span', null, u.correo), u.dependencia ? h('span', null, u.dependencia) : null),
      ))),
      h('form', {
        clase: 'tarjeta apilado separado',
        onsubmit: async (evento) => {
          evento.preventDefault();
          error.textContent = '';
          try {
            const r = await post('/usuarios', { correo: correo.value, nombre: nombre.value, rol: rol.value, dependencia: dependencia.value });
            claveTemporal('Usuario creado', r.clave_temporal, `Contraseña temporal para ${correo.value}:`);
            refrescar();
          } catch (fallo) { error.textContent = fallo.message; }
        },
      },
        h('h2', null, 'Agregar una persona'),
        h('div', { clase: 'fila' }, h('label', { clase: 'campo' }, 'Correo', correo), h('label', { clase: 'campo' }, 'Nombre', nombre)),
        h('div', { clase: 'fila' }, h('label', { clase: 'campo' }, 'Rol', rol), h('label', { clase: 'campo' }, 'Dependencia', dependencia, h('small', null, 'Los administradores no la necesitan.'))),
        error,
        h('div', null, h('button', { clase: 'boton primario', type: 'submit' }, 'Crear cuenta')),
      ),
    );
  }

  // ---------- Ajustes ----------
  async function vistaAjustes(destino) {
    const [a, ia] = await Promise.all([api('/ajustes'), api('/ia')]);
    const esAdmin = yo.rol === 'admin';
    const nombre = h('input', { type: 'text', valor: a.nombre, maxlength: 40, disabled: !esAdmin });
    const bienvenida = h('textarea', { maxlength: 400, disabled: !esAdmin, clase: 'corto' }, a.bienvenida);
    const sugAsp = h('textarea', { disabled: !esAdmin, clase: 'corto' }, a.sugerencias_aspirante.join('\n'));
    const sugEst = h('textarea', { disabled: !esAdmin, clase: 'corto' }, a.sugerencias_estudiante.join('\n'));
    const iaActiva = h('input', { type: 'checkbox', checked: !!a.ia_activa, disabled: !esAdmin });
    const tope = h('input', { type: 'number', min: 0, max: 100000, valor: a.max_llamadas_ia_dia ?? '', placeholder: String(a.tope_servidor), disabled: !esAdmin });
    const error = h('p', { clase: 'error', role: 'alert' });
    destino.replaceChildren(
      titulo('Ajustes', esAdmin ? 'Cómo se presenta y se comporta el asistente. Los cambios aplican de inmediato.' : 'Solo un administrador puede cambiar estos ajustes.'),
      h('form', {
        clase: 'tarjeta apilado',
        onsubmit: async (evento) => {
          evento.preventDefault();
          error.textContent = '';
          try {
            await post('/ajustes', {
              nombre: nombre.value, bienvenida: bienvenida.value, sugerencias_aspirante: sugAsp.value, sugerencias_estudiante: sugEst.value,
              ia_activa: iaActiva.checked, max_llamadas_ia_dia: tope.value === '' ? null : Number(tope.value),
            });
            avisar('Ajustes guardados. El chat ya los usa.');
          } catch (fallo) { error.textContent = fallo.message; }
        },
      },
        h('label', { clase: 'campo' }, 'Nombre del asistente', nombre),
        h('label', { clase: 'campo' }, 'Mensaje de bienvenida', bienvenida),
        h('div', { clase: 'fila' },
          h('label', { clase: 'campo' }, 'Sugerencias para aspirantes', sugAsp, h('small', null, 'Una por línea, máximo 6.')),
          h('label', { clase: 'campo' }, 'Sugerencias para estudiantes', sugEst, h('small', null, 'Una por línea, máximo 6.')),
        ),
        h('label', { clase: 'marca' }, iaActiva, 'Usar IA para redactar respuestas (si se apaga, responde con lo aprobado y el texto oficial)'),
        h('label', { clase: 'campo campo-corto' }, 'Tope diario de llamadas a la IA', tope, h('small', null, `Vacío = el del servidor (${a.tope_servidor}). Al llegar al tope sigue respondiendo sin IA.`)),
        error,
        esAdmin ? h('div', null, h('button', { clase: 'boton primario', type: 'submit' }, 'Guardar ajustes')) : null,
      ),
      h('div', { clase: 'tarjeta separado' },
        h('h2', null, 'Servicios de IA'),
        h('p', { clase: 'suave' }, ia.proveedores.length
          ? 'Se intentan en este orden; si uno falla o se queda sin cuota, responde el siguiente.'
          : 'No hay ninguno configurado. Todos tienen opción gratuita: agrega GEMINI_API_KEY, GROQ_API_KEY o COHERE_API_KEY en el archivo .env del servidor.'),
        ia.proveedores.length ? h('ol', { clase: 'pasos' }, ia.proveedores.map((p) => h('li', null, `${p.nombre} · ${p.modelo}`))) : null,
        h('p', { clase: 'suave' }, `Búsqueda por significado: ${ia.busqueda.nombre === 'ninguna' ? 'desactivada' : ia.busqueda.nombre + (ia.busqueda.modelo ? ' · ' + ia.busqueda.modelo : '')}.`),
      ),
    );
  }

  async function iniciar() {
    try {
      yo = await api('/yo');
    } catch (fallo) {
      pintarEntrada();
      return;
    }
    if (yo.debe_cambiar_clave) {
      pintarCambioObligatorio();
      return;
    }
    ir('inicio');
  }

  iniciar();
})();
