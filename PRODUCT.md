# Product

## Register

product

## Users

Primo utente: il creatore dell'esperimento, che osserva uno o più agenti IA gestire portafogli crypto simulati (paper trading su prezzi reali) e vuole capire, a colpo d'occhio e in profondità, cosa fanno e perché. Contesto d'uso: monitoraggio ricorrente di una run in corso (giorni/settimane), spesso di sfuggita ("come sta andando?") e a volte in sessioni di analisi più lunghe. Pubblico secondario: spettatori a cui mostrare l'esperimento (es. "IA vs investimento conservativo") — l'interfaccia deve restare leggibile e d'impatto anche per chi non l'ha costruita. Lavoro da svolgere: leggere lo stato e la storia di ogni agente (equity, posizioni, operazioni, ragionamento) e confrontarlo con benchmark passivi.

## Product Purpose

Crypto-bot è la piattaforma di osservazione di un esperimento: agenti IA autonomi che fanno paper trading in condizioni realistiche (prezzi live, fee e spread modellati). La tesi non è "predire il mercato" ma vedere se un agente che **non dorme e sintetizza informazione** in continuo ottiene un vantaggio osservabile rispetto a un agente "cieco" e a una scelta passiva. La dashboard è la finestra su questo: deve rendere immediato il confronto IA-vs-benchmark e trasparente il comportamento di ogni agente. Successo = guardandola si capisce in pochi secondi chi sta vincendo e, scavando, *perché* un agente ha fatto quello che ha fatto. È un esperimento ludico e osservativo, non un terminale di trading da produzione.

## Brand Personality

Sala di controllo con brio. Tre parole: **vivo, lucido, schietto**. Deve trasmettere la sensazione di un esperimento *in corso e pulsante* — densità e precisione da control-room, ma con personalità, non un report statico né un cruscotto aziendale anonimo. Voce: diretta e senza fronzoli, niente hype. La serietà viene dall'onestà dei numeri, non da gravità decorativa.

## Anti-references

(L'utente non ha preferenze forti; queste sono scelte di giudizio.)
- **Dashboard SaaS generica**: card tutte uguali, template "big number + label", sfondo cream/sand, eyebrow in maiuscoletto tracciato sopra ogni sezione, icona in tile arrotondata sopra ogni titolo. Lo slop riconoscibile dell'IA.
- **Trading platform da bucket-shop**: rosso/verde saturi ovunque, numeri lampeggianti, estetica da gioco d'azzardo che spinge all'azione. Qui nessuno deve "agire" — si osserva.
- **Cripto-hype**: gradienti neon, "to the moon", estetica lambo/luna. Mina la credibilità dell'esperimento.

## Design Principles

- **Osservazione, non rumore.** L'interfaccia esiste per *leggere* cosa fanno gli agenti; la chiarezza batte la decorazione. Ogni elemento guadagna il suo posto.
- **Numeri onesti.** Mostra P&L reale comprensivo di costi (fee/spread); mai lusingare il bot. La fiducia nasce dalla trasparenza, non dall'abbellimento.
- **Mostra il ragionamento.** Non solo l'esito ma il *perché*: operazioni, eventi e (in futuro) la memoria/idee dell'agente. È il cuore della tesi "edge da sintesi d'informazione".
- **Confrontabile a colpo d'occhio.** IA vs benchmark sempre direttamente paragonabili, dalla stessa base.
- **Esperimento vivo.** Deve percepirsi in movimento e in corso — control-room con personalità — senza diventare un luna park.

## Accessibility & Inclusion

Target WCAG 2.1 AA. Contrasto del testo ≥4.5:1 (≥3:1 per il testo grande). **Non affidare informazione al solo colore**: poiché su/giù e BUY/SELL useranno il colore, accompagnarlo sempre con segno/etichetta/icona (sicurezza per daltonici, ~8% degli uomini). Supporto `prefers-reduced-motion` per ogni animazione (crossfade o transizione istantanea come alternativa).
