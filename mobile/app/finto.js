/* SmartDesk mobile – modalità di prova (?prova): imita l'Apps Script con dati finti, senza collegarsi a niente. */
(function () {
  const oggi = new Date();
  const g = n => { const d = new Date(oggi); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const a0 = oggi.getMonth() >= 8 ? oggi.getFullYear() : oggi.getFullYear() - 1;
  const stato = {
    richieste: [
      { id: 'R1', inizio: `${a0}-10-13`, fine: `${a0}-10-14`, stato: 'DEF', stato_nome: 'Registrata', tipo: 'motivi_personali', descrizione: 'Permesso per motivi personali o familiari', oraria: false, annullabile: true },
      { id: 'R2', inizio: `${a0}-10-22`, fine: `${a0}-10-22`, stato: 'DEF', stato_nome: 'Registrata', tipo: 'motivi_personali', descrizione: 'Permesso per motivi personali o familiari', oraria: false, annullabile: true },
      { id: 'R3', inizio: g(9), fine: g(10), stato: 'FWD', stato_nome: 'Inoltrata', tipo: 'ferie', descrizione: 'Ferie', oraria: false, annullabile: true },
    ],
    assenze: [
      { inizio: `${a0}-10-13`, fine: `${a0}-10-14`, giorni: 2, ore: 0, oraria: false, tipo: 'motivi_personali', descrizione: 'Permesso per motivi personali o familiari', richiesta: 'R1' },
      { inizio: `${a0}-10-22`, fine: `${a0}-10-22`, giorni: 1, ore: 0, oraria: false, tipo: 'motivi_personali', descrizione: 'Permesso per motivi personali o familiari', richiesta: 'R2' },
      { inizio: `${a0}-11-03`, fine: `${a0}-11-03`, giorni: 1, ore: 0, oraria: false, tipo: 'altro', descrizione: 'Assenza per malattia', richiesta: '' },
    ],
    bacheca: [
      { pk: 'A1', titolo: 'Circolare n. 110 – Corsi Piano Estate: avvio e iscritti', categoria: 'Circolari', data: g(-1), n_allegati: 1, pv_richiesta: true, pv_fatta: false, ad_richiesta: false },
      { pk: 'A2', titolo: 'Circolare n. 106 – Assemblea sindacale di lunedì', categoria: 'Circolari', data: g(-2), n_allegati: 1, pv_richiesta: true, pv_fatta: false, ad_richiesta: true, ad_fatta: false, ad_scadenza: g(1), ad_modificabile: true },
      { pk: 'A3', titolo: 'Sciopero del comparto scuola – comunicazione di adesione', categoria: 'Circolari', data: g(-4), n_allegati: 0, pv_richiesta: false, ad_richiesta: true, ad_fatta: false, ad_scadenza: g(0), ad_modificabile: true },
      { pk: 'A4', titolo: 'Circolare n. 104 – Permessi per diritto allo studio', categoria: 'Circolari', data: g(-6), n_allegati: 1, pv_richiesta: true, pv_fatta: false, ad_richiesta: false },
      { pk: 'A5', titolo: 'Disponibilità per le uscite didattiche', categoria: 'Avvisi', data: g(-8), n_allegati: 0, pv_richiesta: false, ad_richiesta: true, ad_fatta: false, ad_scadenza: g(-1), ad_modificabile: true },
      { pk: 'A6', titolo: 'Circolare n. 098 – Calendario dei consigli di classe', categoria: 'Circolari', data: g(-12), n_allegati: 1, pv_richiesta: true, pv_fatta: true, pv_quando: '05/11/' + (a0 + 1), ad_richiesta: false },
    ],
  };
  const dati = () => ({ dal: `${a0}-09-01`, al: `${a0 + 1}-08-31`, assenze: stato.assenze, richieste: stato.richieste });
  const daFare = m => (m.pv_richiesta && !m.pv_fatta) || (m.ad_richiesta && !m.ad_fatta);
  const pausa = ms => new Promise(r => setTimeout(r, ms));
  const errore = (msg, codice = 400) => ({ ok: false, errore: msg, codice });
  window.FINTO = async function (c) {
    await pausa(350);
    switch (c.azione) {
      case 'accedi':
        if (!c.utente || !c.password) return errore('Scrivi nome utente e password di Argo.');
        return { ok: true, sessione: 'prova', nome: 'Giulia', cognome: 'Rinaldi', dati: dati() };
      case 'dati': return { ok: true, dati: dati() };
      case 'annulla': {
        const r = stato.richieste.find(x => x.id === c.richiesta);
        if (!r || !r.annullabile) return errore('Richiesta non trovata.');
        if (!c.motivo || c.motivo.length > 250) return errore('Il motivo deve avere da 1 a 250 caratteri.');
        r.stato = r.stato === 'DEF' ? 'NOF' : 'NUL'; r.stato_nome = r.stato === 'NOF' ? 'Annullata dopo la registrazione' : 'Annullata'; r.annullabile = false;
        return { ok: true, messaggio: 'Annullamento inviato', allegati_non_caricati: [], dati: dati() };
      }
      case 'bacheca': return { ok: true, messaggi: stato.bacheca.map(m => ({ ...m })), da_fare: stato.bacheca.filter(daFare).length };
      case 'conferma': {
        await pausa(500);
        const m = stato.bacheca.find(x => x.pk === c.pk);
        if (!m) return errore('Messaggio non trovato.');
        if (c.adesione) { m.ad_fatta = true; m.adesione = c.adesione; } else { m.pv_fatta = true; m.pv_quando = new Date().toLocaleDateString('it-IT'); }
        return { ok: true, messaggio: { ...m }, aperti: m.n_allegati };
      }
      case 'allegati': return { ok: true, allegati: [{ nome: 'circolare-di-prova.pdf', url: 'icona.svg' }] };
      case 'esci': return { ok: true };
      default: return errore('Azione non prevista.');
    }
  };
})();
