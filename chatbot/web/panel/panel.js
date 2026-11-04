/**
 * Panel de funcionarios. Sin dependencias ni paso de compilación.
 * Todo el contenido se pinta con textContent: lo que se escribe en el panel nunca se interpreta como HTML.
 */
(function () {
  'use strict';

  const app = document.getElementById('app');
  const avisos = document.getElementById('avisos');
  const ESTADOS = { publicado: 'Publicado', revision: 'En revisión', borrador: 'Borrador', archivado: 'Archivado' };
  const NOMBRE_TITULO = { faq: 'Pregunta', fecha: 'Nombre del evento', contacto: 'Oficina', articulo: 'Título' };
  const NOMBRE_TEXTO = { faq: 'Respuesta aprobada', fecha: 'Descripción', contacto: 'Datos de contacto', articulo: 'Texto de la norma' };
  const NOMBRE_NUEVO = { faq: 'Nueva pregunta frecuente', fecha: 'Nueva fecha', contacto: 'Nuevo contacto', articulo: 'Nueva norma' };

  let yo = null;
  let vistaActual = 'inicio';
  let filtros = { tipo: '', estado: '', dependencia: '', q: '', pagina: 1 };

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

  function fechaCorta(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' });
  }

  function etiquetaEstado(item) {
    const lista = [h('span', { clase: 'etiqueta ' + item.estado }, ESTADOS[item.estado])];
    if (item.pendiente_estado) {
      lista.push(h('span', { clase: 'etiqueta ' + item.pendiente_estado }, item.pendiente_estado === 'revision' ? 'Cambio en revisión' : 'Cambio en borrador'));
    }
    return lista;
  }

  // ---------- Entrada ----------
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
      h('div', null, h('h1', null, 'Panel del asistente'), h('p', null, 'Administra lo que responde el asistente estudiantil.')),
      h('label', { clase: 'campo' }, 'Correo', correo),
      h('label', { clase: 'campo' }, 'Contraseña', clave),
      error,
      boton,
      h('p', null, 'En producción se entraría con el correo institucional.'),
    );
    app.replaceChildren(h('div', { clase: 'entrada' }, formulario));
    correo.focus();
  }

  // ---------- Estructura ----------
  const VISTAS = [
    ['inicio', 'Inicio', vistaInicio],
    ['contenido', 'Contenido', vistaContenido],
    ['revision', 'Revisión', vistaRevision],
    ['sin', 'Sin respuesta', vistaSinRespuesta],
    ['importar', 'Importar documento', vistaImportar],
    ['probar', 'Probar el asistente', vistaProbar],
    ['actividad', 'Actividad', vistaActividad],
  ];

  async function pintarEstructura() {
    const resumen = await api('/resumen');
    const contadores = { revision: resumen.en_revision, sin: resumen.sin_respuesta };
    const nav = h('nav', { 'aria-label': 'Secciones' },
      VISTAS.map(([id, nombre]) => h('button', {
        type: 'button',
        'aria-current': id === vistaActual ? 'page' : null,
        onclick: () => ir(id),
      }, nombre, contadores[id] ? h('span', { clase: 'contador' }, contadores[id]) : null)),
    );
    const principal = h('main', { id: 'vista' });
    app.replaceChildren(h('div', { clase: 'estructura' },
      h('aside', { clase: 'lateral' },
        h('div', { clase: 'marca-panel' }, h('strong', null, 'Asistente estudiantil'), h('span', null, 'Panel de administración')),
        nav,
        h('div', { clase: 'persona' },
          h('div', null, h('strong', null, yo.nombre), h('span', null, yo.nombre_rol + (yo.dependencia ? ' · ' + yo.dependencia : ''))),
          h('button', { type: 'button', onclick: salir }, 'Salir'),
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

  // ---------- Inicio ----------
  async function vistaInicio(destino) {
    const r = await api('/resumen');
    const metrica = (numero, texto, id) => id
      ? h('button', { clase: 'metrica', type: 'button', onclick: () => ir(id) }, h('strong', null, numero), h('span', null, texto))
      : h('div', { clase: 'metrica' }, h('strong', null, numero), h('span', null, texto));
    destino.replaceChildren(
      titulo('Inicio', 'Hola, ' + yo.nombre + '. Esto es lo que está pasando con el asistente.'),
      h('div', { clase: 'metricas' },
        metrica(r.en_revision, 'Esperan revisión', 'revision'),
        metrica(r.sin_respuesta, 'Preguntas sin respuesta', 'sin'),
        metrica(r.preguntas_hoy, 'Preguntas hoy'),
        metrica(r.publicados.faq || 0, 'Preguntas frecuentes publicadas', 'contenido'),
        metrica(r.publicados.articulo || 0, 'Artículos vigentes', 'contenido'),
      ),
      h('div', { clase: 'tarjeta estado-ia' },
        h('span', { clase: 'punto' + (r.ia ? '' : ' apagado') }),
        h('div', null,
          h('h2', null, r.ia ? 'Redacción con IA activa' : 'Modo sin IA'),
          h('p', null, r.ia
            ? `Hoy se han usado ${r.llamadas_ia_hoy} de ${r.tope_ia} llamadas. Al llegar al tope, el asistente sigue respondiendo sin IA.`
            : 'El asistente responde con las preguntas aprobadas y cita el texto literal de la norma. Para que redacte en lenguaje sencillo, agrega una clave de Cohere.'),
        ),
      ),
      h('div', { clase: 'tarjeta' },
        h('h2', null, 'Cómo se actualiza una respuesta'),
        h('ol', { clase: 'pasos' },
          h('li', null, 'Un editor cambia el contenido de su dependencia. El público sigue viendo la versión anterior.'),
          h('li', null, 'Lo comprueba en «Probar el asistente», que ya usa los cambios pendientes.'),
          h('li', null, 'Lo envía a revisión y un aprobador lo publica. El cambio aplica de inmediato.'),
          h('li', null, 'Cada cambio queda en el historial y se puede restaurar.'),
        ),
      ),
    );
  }

  // ---------- Contenido ----------
  function filaContenido(item) {
    const vista = item.vista;
    const meta = [item.dependencia];
    if (item.fuente) meta.push(item.fuente);
    if (item.fecha_legible) meta.push(item.fecha_legible);
    return h('button', { clase: 'item', type: 'button', onclick: () => abrirEditor(item.id) },
      h('strong', null, vista.titulo),
      h('span', { clase: 'etiquetas' }, h('span', { clase: 'etiqueta tipo' }, yo.tipos[item.tipo]), etiquetaEstado(item)),
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
          h('span', null, `${datos.total} resultados`),
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
      titulo('Contenido', 'Lo que el asistente puede responder.',
        h('div', { clase: 'etiquetas' },
          Object.entries(NOMBRE_NUEVO).filter(([tipo]) => tipo !== 'articulo').map(([tipo, nombre]) =>
            h('button', { clase: 'boton' + (tipo === 'faq' ? ' primario' : ''), type: 'button', onclick: () => abrirNuevo(tipo) }, nombre)),
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
        selector('dependencia', 'Todas las dependencias', Object.fromEntries(yo.dependencias.map((d) => [d, d]))),
      ),
      contenedor,
    );
    await cargar();
  }

  // ---------- Editor ----------
  function dialogo(contenido) {
    const nodo = h('dialog', { 'aria-label': 'Editor' }, contenido);
    nodo.addEventListener('close', () => nodo.remove());
    document.body.append(nodo);
    nodo.showModal();
    return nodo;
  }

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
    };
    const nodos = [
      h('label', { clase: 'campo' }, NOMBRE_TITULO[tipo], campos.titulo),
      h('label', { clase: 'campo' }, NOMBRE_TEXTO[tipo], campos.texto,
        tipo === 'faq' ? h('small', null, 'Se muestra tal cual. Usa **negrita**, y líneas con «- » o «1. » para hacer listas.') : null),
    ];
    if (tipo === 'fecha') {
      nodos.push(h('div', { clase: 'fila' },
        h('label', { clase: 'campo' }, 'Desde (opcional)', campos.inicio),
        h('label', { clase: 'campo' }, 'Hasta', campos.fin, h('small', null, 'Después de este día deja de mostrarse sola.')),
      ));
    }
    if (tipo === 'articulo') nodos.push(h('label', { clase: 'campo' }, 'Capítulo', campos.capitulo));
    nodos.push(h('label', { clase: 'campo' }, 'Enlace oficial', campos.url));
    if (tipo === 'faq') nodos.push(h('label', { clase: 'marca' }, campos.destacada, 'Mostrar como sugerencia al abrir el chat'));
    const leer = () => ({
      titulo: campos.titulo.value,
      texto: campos.texto.value,
      url: campos.url.value,
      inicio: campos.inicio.value,
      fin: campos.fin.value,
      capitulo: campos.capitulo.value,
      destacada: campos.destacada.checked,
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
    const soloLectura = !datos.puede_editar || datos.estado === 'archivado';
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
    if (datos.nota_revision) avisosEditor.push(h('p', { clase: 'nota' }, 'Devuelto por el aprobador: ' + datos.nota_revision));
    if (datos.reemplazado_por) avisosEditor.push(h('p', { clase: 'nota' }, 'Esta versión fue reemplazada por una norma posterior.'));
    if (!datos.puede_editar) avisosEditor.push(h('p', { clase: 'nota info' }, `Este contenido es de ${datos.dependencia}. Puedes verlo, pero no cambiarlo.`));
    if (datos.fuente_nota) avisosEditor.push(h('p', { clase: 'nota info' }, datos.fuente_nota));

    // El aprobador debe ver lo que cambia, sea el texto, la fecha o el enlace.
    const version = (v) => [
      v.titulo,
      v.fin ? 'Fecha: ' + [v.inicio, v.fin].filter(Boolean).filter((f, i, l) => l.indexOf(f) === i).join(' a ') : '',
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
    if (datos.puede_editar && hayPendiente && !enRevision) {
      botones.push(h('button', { clase: 'boton primario', type: 'button', onclick: accion('enviar', 'Enviado a revisión.') }, 'Enviar a revisión'));
    }
    if (datos.puede_publicar && enRevision) {
      botones.push(h('button', { clase: 'boton', type: 'button', onclick: devolver }, 'Devolver'));
    }
    if (datos.puede_publicar && hayPendiente) {
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
          datos.puede_editar && indice > 0
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

  // ---------- Sin respuesta ----------
  async function vistaSinRespuesta(destino) {
    const filas = await api('/sin-respuesta');
    destino.replaceChildren(
      titulo('Preguntas sin respuesta', 'Lo que la gente preguntó y el asistente no pudo responder. Se guardan sin correos ni números de documento.'),
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
      const error = h('p', { clase: 'error', role: 'alert' });
      const piezas = [];
      datos.advertencias.forEach((texto) => piezas.push(h('p', { clase: datos.es_escaneo ? 'nota error-caja' : 'nota' }, texto)));
      if (datos.segmentos.length) {
        piezas.push(h('form', {
          clase: 'tarjeta apilado',
          onsubmit: async (evento) => {
            evento.preventDefault();
            try {
              const r = await post('/importar/confirmar', { nombre: nombre.value, dependencia: dependencia.value, url: url.value, segmentos: datos.segmentos });
              avisar(`Se crearon ${r.creados} borradores.`);
              filtros = { tipo: 'articulo', estado: 'borrador', dependencia: '', q: '', pagina: 1 };
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
          h('label', { clase: 'campo' }, 'Enlace oficial', url),
          h('div', { clase: 'segmentos' }, datos.segmentos.map((s) => h('div', { clase: 'segmento' }, h('strong', null, s.titulo), h('p', null, s.texto)))),
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
      h('div', { clase: 'burbuja bot' }, 'Este chat ya usa los borradores y cambios en revisión. Solo lo ves tú: no afecta al público.'));
    const entrada = h('input', { type: 'text', placeholder: 'Escribe una pregunta de prueba', 'aria-label': 'Pregunta de prueba', maxlength: 500 });
    const boton = h('button', { clase: 'boton primario', type: 'submit' }, 'Preguntar');
    const historial = [];
    const NOMBRES = { aprobada: 'Respuesta aprobada', ia: 'Redactada con IA', norma: 'Texto de la norma', sin_informacion: 'Sin información', personal: 'Dato personal', fuera_de_tema: 'Fuera de tema', saludo: 'Saludo', apoyo: 'Apoyo', reintentar: 'La IA no respondió a tiempo' };
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
              const r = await post('/probar', { pregunta, historial: historial.slice(-6) });
              const fuentes = r.fuentes.map((f) => f.titulo + (f.borrador ? ' (sin publicar)' : '')).join(' · ');
              mensajes.append(h('div', { clase: 'burbuja bot' }, conNegrita(r.respuesta), h('small', null, [NOMBRES[r.tipo] || r.tipo, fuentes].filter(Boolean).join(' — '))));
              historial.push({ rol: 'usuario', texto: pregunta }, { rol: 'asistente', texto: r.respuesta.slice(0, 600) });
            } catch (fallo) {
              avisar(fallo.message, true);
            }
            boton.disabled = false;
            mensajes.scrollTop = mensajes.scrollHeight;
            entrada.focus();
          },
        }, entrada, boton),
      ),
    );
    entrada.focus();
  }

  // ---------- Actividad ----------
  async function vistaActividad(destino) {
    const filas = await api('/actividad');
    destino.replaceChildren(
      titulo('Actividad', 'Quién cambió qué y cuándo.'),
      filas.length
        ? h('div', { clase: 'lista' }, filas.map((fila) => h('button', { clase: 'item', type: 'button', onclick: () => abrirEditor(fila.contenido_id) },
          h('strong', null, fila.titulo),
          h('span', { clase: 'etiquetas' }, h('span', { clase: 'etiqueta tipo' }, fila.accion.split(':')[0])),
          h('span', { clase: 'meta' }, h('span', null, fila.autor), h('span', null, fila.dependencia), h('span', null, fechaCorta(fila.fecha))),
        )))
        : h('div', { clase: 'lista' }, h('div', { clase: 'vacio' }, 'Todavía no hay cambios registrados.')),
    );
  }

  async function iniciar() {
    try {
      yo = await api('/yo');
    } catch (fallo) {
      pintarEntrada();
      return;
    }
    ir('inicio');
  }

  iniciar();
})();
