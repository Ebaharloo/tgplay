import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge, Button, Card, CheckboxInput, DropdownMenu, Heading, Selector,
  Tab, TabList, Text, TextInput,
} from '@astryxdesign/core'

import { get, post } from './api.js'

const LIGHT = { ok: 'success', warn: 'warning', bad: 'error' }
const NAMES = { simkl: 'Simkl', gate: 'AnimeGate', anilist: 'AniList' }
const SHORT = {
  quality: 'Quality', audio: 'Audio', skip: 'Skip', toggle: 'T toggle',
  next: 'next ep', nowait: 'at cut', sync: 'Simkl sync', full: 'fullscreen',
  cut: 'Cut last N s', extra: 'Extra mpv flags',
}

// The window shares one snapshot: poll it, and let SSE push log lines.
function useSnapshot() {
  const [snap, setSnap] = useState(null)
  const [down, setDown] = useState('')
  useEffect(() => {
    let live = true
    let timer
    const tick = async () => {
      try {
        const s = await get('/api/state')
        if (live) { setSnap(s); setDown('') }
      } catch (e) {
        if (live) setDown(e.message)
      }
      if (live) timer = setTimeout(tick, 1500)
    }
    tick()
    return () => { live = false; clearTimeout(timer) }
  }, [])
  return [snap, down]
}

// The server sends the log tail in bursts (EventSource reconnects); the
// status strip only needs the newest line.
function useLog() {
  const [line, setLine] = useState('')
  useEffect(() => {
    const es = new EventSource('/api/events')
    es.onmessage = (e) => {
      try { setLine(JSON.parse(e.data).line || '') } catch { /* keepalive */ }
    }
    return () => es.close()
  }, [])
  return line
}

function initials(title) {
  return (title || '?').split(/\s+/).slice(0, 2).map((w) => w[0] || '')
    .join('').toUpperCase()
}

// Same pages gui_all._page_links builds: ids when pinned, a search otherwise.
function pages(title, ids = {}) {
  const q = encodeURIComponent(title || '')
  const out = []
  out.push(ids.simkl ? ['Simkl', `https://simkl.com/anime/${ids.simkl}/`]
    : ['Simkl search', `https://simkl.com/search/?q=${q}`])
  out.push(ids.anilist ? ['AniList', `https://anilist.co/anime/${ids.anilist}`]
    : ['AniList search', `https://anilist.co/search/anime?search=${q}`])
  out.push(ids.mal ? ['MyAnimeList', `https://myanimelist.net/anime/${ids.mal}`]
    : ['MyAnimeList search', `https://myanimelist.net/anime.php?q=${q}`])
  out.push(['Fandom search', `https://www.fandom.com/?s=${q}`])
  return out
}

function Poster({ item, onPick }) {
  const sub = item.days_ago === 0 ? 'today' : `${item.days_ago}d ago`
  return (
    <button type="button" className="poster" onClick={onPick} title={item.title}>
      {item.image
        ? <img className="art" src={item.image} alt="" loading="lazy" />
        : <span className="art ph">{initials(item.title)}</span>}
      <span className="t">{item.title}</span>
      <span className="s">{sub}{item.behind ? ` · +${item.behind}` : ''}</span>
      <span className="bar"><i style={{ width: `${Math.round(item.pct || 0)}%` }} /></span>
    </button>
  )
}

function Rail({ snap, onPick }) {
  const [tab, setTab] = useState('recent')
  const items = (snap.rails && snap.rails[tab]) || []
  return (
    <Card padding={3}>
      <div className="row" style={{ alignItems: 'center', marginBottom: '8px' }}>
        <TabList value={tab} onChange={setTab} size="sm">
          <Tab value="continue" label="▶ Continue watching" />
          <Tab value="recent" label="🆕 Recently aired" />
        </TabList>
        <Badge label={String(items.length)} />
        <span className="grow" />
        <Text size="sm" tone="secondary">
          {tab === 'continue' ? 'next unwatched episode' : `${snap.rails_settings?.recent?.days || 14} days`}
        </Text>
      </div>
      <div className="rail">
        {items.length
          ? items.map((it) => (
            <Poster key={`${it.simkl}-${it.title}`} item={it}
              onPick={() => onPick(it.title)} />
          ))
          : <Text size="sm" tone="secondary">nothing here yet — refresh the feed ↻</Text>}
      </div>
    </Card>
  )
}

function Options({ fields, setFields, hasSession }) {
  const set = (k, patch) => setFields(
    fields.map((f) => (f.k === k ? { ...f, ...patch } : f)))
  const choices = fields.filter((f) => f.kind === 'choice')
  const flags = fields.filter((f) => f.kind === 'flag')
  const texts = fields.filter((f) => f.kind === 'text')
  return (
    <div className={'opts' + (hasSession ? '' : ' opts-off')}>
      <div className="row">
        {choices.map((f) => (
          <Selector key={f.k} label={SHORT[f.k] || f.k} isLabelHidden
            options={f.choices} value={f.choices[f.i] || f.choices[0]}
            size="sm" width={f.k === 'quality' ? 158 : 96}
            isDisabled={!hasSession}
            onChange={(v) => set(f.k, { i: Math.max(0, f.choices.indexOf(v)) })} />
        ))}
      </div>
      <div className="checks">
        {flags.map((f) => (
          <CheckboxInput key={f.k} label={SHORT[f.k] || f.k} size="sm"
            value={!!f.val} isDisabled={!hasSession}
            onChange={(v) => set(f.k, { val: v })} />
        ))}
      </div>
      <div className="row">
        {texts.map((f) => (
          <TextInput key={f.k} label={SHORT[f.k] || f.k} isLabelHidden size="sm"
            width={f.k === 'cut' ? 96 : 240} value={String(f.val ?? '')}
            placeholder={SHORT[f.k]} isDisabled={!hasSession}
            onChange={(v) => set(f.k, { val: v })} />
        ))}
      </div>
    </div>
  )
}

function Results({ search, onOpen, say }) {
  const [pick, setPick] = useState(-1)
  const rows = search.results || []
  useEffect(() => { setPick(-1) }, [search.q, rows.length])
  const move = (d) => setPick((i) => Math.min(rows.length - 1, Math.max(0, i + d)))
  return (
    <Card padding={0}>
      <div className="row" style={{ padding: '10px', alignItems: 'center' }}>
        <Heading level={6}>
          {search.busy ? 'Searching…'
            : `Results${rows.length ? ` · ${rows.length} for “${search.q}”`
              : search.q ? ` · no hits for “${search.q}”` : ' · nothing yet'}`}
        </Heading>
        <span className="grow" />
        {search.busy && <Badge label="busy" variant="info" />}
      </div>
      <div className="list" tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); move(1) }
          if (e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
          if (e.key === 'Enter' && rows[pick]) onOpen(rows[pick])
        }}>
        {rows.map((r, i) => (
          <div key={`${r.source}-${r.url}-${i}`}
            className={i === pick ? 'item sel' : 'item'}>
            <span className="name" title={r.url}
              onClick={() => { setPick(i); onOpen(r) }}>{r.title}</span>
            <Badge label={r.source || '?'} variant="neutral" />
            {r.matched === 'id' && <Badge label="same id" variant="success" />}
            <DropdownMenu size="sm"
              button={{ label: '⋯', variant: 'ghost', size: 'sm' }}
              items={[
                { label: '⧉ Copy link', onClick: () => say(copy(r.url)) },
                { label: '🔗 Open in browser', href: r.url },
                { type: 'divider' },
                {
                  type: 'section', title: 'Show pages',
                  items: pages(r.title, r.ids).map(([l, u]) => ({ label: l, href: u })),
                },
              ]} />
          </div>
        ))}
      </div>
    </Card>
  )
}

function EpisodeRow({ ep, isSel, isFocus, onSelect, onPlayFrom, say, title, ids }) {
  const items = [
    { label: '▶ Play from here to the end', onClick: () => onPlayFrom(ep.num) },
    { label: '▶ Play only selected', onClick: () => onPlayFrom(ep.num, true) },
    { label: '▶ Play all', onClick: () => onPlayFrom(0) },
    { type: 'divider' },
    { label: '⧉ Copy episode link', onClick: () => say(copy(ep.link || '')) },
    {
      type: 'section', title: 'Show pages',
      items: pages(title, ids).map(([l, u]) => ({ label: l, href: u })),
    },
  ]
  return (
    <div className={isSel || isFocus ? 'item sel' : 'item'}
      onContextMenu={(e) => { e.preventDefault(); onSelect(ep.num) }}>
      <span className="num">{ep.num}</span>
      <span className="name" onClick={() => onSelect(ep.num)}
        onDoubleClick={() => onPlayFrom(ep.num)}>{ep.name}</span>
      <DropdownMenu button={{ label: '⋯', variant: 'ghost', size: 'sm' }}
        items={items} />
    </div>
  )
}

function Show({ session, sel, setSel, focus, setFocus, onPlay, say }) {
  const eps = session.episodes || []
  const ids = session.mal ? { mal: session.mal } : {}
  const key = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const at = eps.findIndex((x) => x.num === focus)
      const next = eps[Math.min(eps.length - 1,
        Math.max(0, at + (e.key === 'ArrowDown' ? 1 : -1)))]
      if (next) { setFocus(next.num); setSel([next.num]) }
    }
    if (e.key === 'Enter' && focus != null) onPlay(fromHere(focus))
  }
  const fromHere = (num) => (num ? eps.filter((x) => x.num >= num) : eps)
    .map((x) => x.num)
  return (
    <Card padding={0} style={{ flex: '1 1 auto', minHeight: 0 }}>
      <div className="row" style={{ padding: '10px', alignItems: 'center' }}>
        <Heading level={5}>{session.title} · {eps.length} eps</Heading>
        <Badge label={session.src} />
        {session.mal && <Badge label={`mal ${session.mal}`} variant="neutral" />}
        <span className="grow" />
        <Button label={`▶ Play selected (${sel.length || 1})`} variant="primary"
          size="sm" isDisabled={!eps.length}
          onClick={() => onPlay(sel.length ? sel : focus ? [focus] : eps.map((e) => e.num))} />
        <Button label={`▶ All (${eps.length})`} size="sm" isDisabled={!eps.length}
          onClick={() => onPlay(eps.map((e) => e.num))} />
      </div>
      {session.link && <div className="mono link">{session.link}</div>}
      <div className="list grow" tabIndex={0} onKeyDown={key}>
        {eps.map((ep) => (
          <EpisodeRow key={ep.num} ep={ep} title={session.title} ids={ids}
            isSel={sel.includes(ep.num)} isFocus={ep.num === focus}
            say={say}
            onSelect={(num) => { setFocus(num); setSel([num]) }}
            onPlayFrom={(num, onlySel) => onPlay(onlySel
              ? (sel.length ? sel : num ? [num] : eps.map((e) => e.num))
              : fromHere(num))} />
        ))}
      </div>
    </Card>
  )
}

function Sidebar({ snap, onRefresh }) {
  const [feedTab, setFeedTab] = useState('aired')
  const aired = snap.feed || []
  const soon = snap.upcoming || []
  return (
    <div className="side">
      <div className="row" style={{ alignItems: 'center' }}>
        {Object.keys(NAMES).map((k) => (
          <Badge key={k} variant={LIGHT[snap.lights?.[k]] || 'neutral'}
            label={`● ${NAMES[k]}`} />
        ))}
        <span className="grow" />
        <Button label="↻" variant="ghost" size="sm" onClick={onRefresh} />
      </div>
      <Card padding={2} style={{ flex: '1 1 auto', minHeight: 0 }}>
        <div className="row" style={{ alignItems: 'center' }}>
          <TabList value={feedTab} onChange={setFeedTab} size="sm">
            <Tab value="aired" label={`Aired ${aired.length}`} />
            <Tab value="upcoming" label={`Upcoming ${soon.length}`} />
          </TabList>
        </div>
        <div className="list tbl fade">
          {feedTab === 'aired' && aired.map((f, i) => (
            <div className="item" key={`${f.title}-${i}`}>
              <span className="mono">{f.days === 0 ? 'today' : `${f.days}d`}</span>
              <span className="mono">{f.ep}</span>
              <span className="name" title={f.title}>{f.title}</span>
              {f.new && <Badge label="new" variant="success" />}
            </div>
          ))}
          {feedTab === 'upcoming' && soon.map((f, i) => (
            <div className="item" key={`${f.title}-${i}`}>
              <span className="mono">{f.date || '—'}</span>
              <span className="mono">{f.ep}</span>
              <span className="name" title={f.title}>{f.title}</span>
            </div>
          ))}
          {feedTab === 'aired' && !aired.length && (
            <Text size="sm" tone="secondary">
              nothing aired in the last 14 days — widen the days in ⚙ settings
            </Text>)}
          {feedTab === 'upcoming' && !soon.length && (
            <Text size="sm" tone="secondary">
              no scheduled episodes — refresh the feed ↻
            </Text>)}
        </div>
      </Card>
      <Card padding={2} style={{ flex: '1 1 auto', minHeight: 0 }}>
        <Heading level={6}>History</Heading>
        <div className="list tbl">
          {(snap.history || []).map((h, i) => (
            <div className="item" key={`${h.title}-${i}`}>
              <span className="mono">{h.watched}</span>
              <span className="mono">{h.prog}</span>
              <span className="name" title={h.title}>{h.title}</span>
            </div>
          ))}
        </div>
      </Card>
      <Button label="↻ refresh feed & history" size="sm" onClick={onRefresh} />
    </div>
  )
}

async function copy(text) {
  if (!text) return 'nothing to copy'
  try {
    await navigator.clipboard.writeText(text)
    return 'copied'
  } catch (e) {
    return `copy failed: ${e.message}`
  }
}

export default function App() {
  const [snap, down] = useSnapshot()
  const log = useLog()
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  const [fields, setFields] = useState([])
  const [sel, setSel] = useState([])
  const [focus, setFocus] = useState(null)
  const box = useRef(null)

  const session = snap?.session
  const link = session?.link || ''

  // New show loaded -> adopt the server's option fields and resume row.
  useEffect(() => {
    if (snap?.opts?.fields) setFields(snap.opts.fields)
    setSel([])
    setFocus(session?.resume ?? session?.episodes?.[0]?.num ?? null)
  }, [link])

  // First snapshot arrives after the effect above ran with an empty link, so
  // the fields stayed [] and the whole options panel rendered blank. Adopt
  // them once, then never overwrite what the user is editing.
  useEffect(() => {
    if (!fields.length && snap?.opts?.fields?.length) {
      setFields(snap.opts.fields)
    }
  }, [snap?.opts?.fields])

  useEffect(() => {
    const onKey = (e) => {
      const typing = /input|textarea|select/i.test(e.target.tagName || '')
      if (e.key === '/' && !typing) {
        e.preventDefault()
        box.current?.querySelector('input')?.focus()
      }
      if (e.key === 'Escape') { setQ(''); setErr('') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const say = (msg) => {
    if (msg) setErr(msg)
    setTimeout(() => setErr(''), 5000)
  }

  const search = async (text) => {
    const want = (text ?? q).trim()
    if (!want) return
    setQ(want)
    try { await post('/api/search', { q: want }) } catch (e) { setErr(e.message) }
  }

  const open = async (row) => {
    try {
      await post('/api/open', { src: row.source, url: row.url })
    } catch (e) { setErr(e.message) }
  }

  const play = async (eps) => {
    if (!eps?.length) return setErr('pick at least one episode')
    try {
      await post('/api/play', {
        eps, fields, opts: snap.opts?.opts || {}, mpv: snap.opts?.mpv || [],
      })
    } catch (e) { setErr(e.message) }
  }

  const refresh = async () => {
    try { await post('/api/settings', { rails: snap.rails_settings || {} }) }
    catch (e) { setErr(e.message) }
  }

  const status = down || err || snap?.status?.message
    || (snap?.status?.playing ? 'playing' : '')
  const last = log

  return (
    <div className="app">
      <div className="col">
        {snap
          ? <Rail snap={snap} onPick={(title) => search(title)} />
          : <Card padding={3}><Text size="sm" tone="secondary">connecting…</Text></Card>}

        <div className="row">
          <div className="field" ref={box}>
            <TextInput label="Search" isLabelHidden value={q} onChange={setQ}
              onEnter={() => search()} placeholder="Search or paste a link"
              hasClear size="md" />
            <div className="row" style={{ marginTop: '6px', alignItems: 'center' }}>
              <Button label="🔎 Search" size="sm" onClick={() => search()} />
              <Text size="sm" tone="secondary">
                name, link or @channel · Enter opens · / focuses · Esc clears
              </Text>
            </div>
          </div>
          <Options fields={fields} setFields={setFields}
            hasSession={!!session} />
        </div>

        <Results search={snap?.search || { q: '', results: [], busy: false }}
          onOpen={open} say={say} />

        <div className="show-slot">
          {session
            ? <Show session={session} sel={sel} setSel={setSel} focus={focus}
              setFocus={setFocus} onPlay={play} say={say} />
            : <Card padding={3} className="fade">
              <Heading level={5}>No show loaded</Heading>
              <Text size="sm" tone="secondary">
                search a title and click a result — the episode list and the
                controls above stay in place and activate for it
              </Text>
            </Card>}
        </div>

        <div className="bottoms">
          <Button label="■ Stop" variant="secondary" size="sm"
            isDisabled={!session}
            onClick={() => post('/api/stop').catch((e) => setErr(e.message))} />
          <Text size="sm" tone="secondary">{status || session?.status || 'idle'}</Text>
          <span className="mono grow">{last}</span>
          <Button label="Close" variant="secondary" size="sm"
            onClick={() => window.close()} />
        </div>
      </div>

      <Sidebar snap={snap || {}} onRefresh={refresh} />
    </div>
  )
}
