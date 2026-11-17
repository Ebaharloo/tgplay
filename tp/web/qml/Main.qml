// The tgplay window as Qt Quick — same layout and tokens as the Astryx web
// build, but the server (`tp/web/server.py`) stays the only source of truth:
// we poll /api/state and POST the same endpoints the browser app uses.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1360
    height: 960
    minimumWidth: 980
    minimumHeight: 640
    visible: true
    title: 'tgplay'
    color: tk.bg

    // astryx theme-neutral tokens; px sizes are the 16px rem base
    readonly property bool dark: Application.styleHints.colorScheme === Qt.ColorScheme.Dark
    readonly property string uiFont: Qt.fontFamilies().indexOf('Figtree') >= 0 ? 'Figtree' : ''
    readonly property string monoFont: Qt.fontFamilies().indexOf('SF Mono') >= 0 ? 'SF Mono' : ''

    QtObject {
        id: tk
        readonly property color bg: win.dark ? '#1b1b1b' : '#f1f1f1'
        readonly property color card: win.dark ? '#1b1b1b' : '#ffffff'
        readonly property color muted: win.dark ? '#262626' : '#f1f1f1'
        readonly property color border: win.dark ? '#1affffff' : '#14000000'
        readonly property color text: win.dark ? '#ffffff' : '#000000'
        readonly property color text2: win.dark ? '#9e9e9e' : '#474747'
        readonly property color accent: win.dark ? '#f1f1f1' : '#1b1b1b'
        readonly property color success: win.dark ? '#64af4c' : '#198100'
        readonly property color error: win.dark ? '#ff705d' : '#c9303a'
        readonly property color info: win.dark ? '#6d9cfe' : '#0074e2'
        readonly property int rEl: 10
        readonly property int rIn: 6
        readonly property int xs: 12
        readonly property int sm: 13
        readonly property int base: 14
        readonly property int lg: 17
    }

    // ---- server state ----------------------------------------------------
    property var snap: null
    property string down: ''
    property string err: ''
    property string logLine: ''
    property string q: ''
    property var fields: []          // editable copy; the poll must not clobber edits
    property var sel: []
    property var focusNum: null
    property string adoptLink: '\u0000'

    readonly property var session: snap ? snap.session : null
    readonly property var episodes: session ? session.episodes : []
    readonly property var watchedEps: session && session.watched ? session.watched.eps : []
    readonly property string status: down || err || (snap && snap.status ? snap.status.message : '')
        || (snap && snap.status && snap.status.playing ? 'playing' : '') || 'idle'

    function api(method, path, body, cb) {
        const xhr = new XMLHttpRequest()
        xhr.open(method, apiBase.replace(/\/$/, '') + path)
        xhr.setRequestHeader('Content-Type', 'application/json')
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            let data = {}
            try { data = JSON.parse(xhr.responseText || '{}') } catch (e) {}
            if (cb) cb(xhr.status >= 200 && xhr.status < 300 ? '' : (data.error || xhr.status), data)
        }
        xhr.send(body === undefined ? null : JSON.stringify(body))
    }

    function fail(msg) { err = msg; errTimer.restart() }
    Timer { id: errTimer; interval: 5000; onTriggered: win.err = '' }

    Timer {
        interval: 1500; running: true; repeat: true; triggeredOnStart: true
        onTriggered: api('GET', '/api/state', undefined, function (e, d) {
            if (e) { win.down = e; return }
            win.down = ''
            win.snap = d
            win.adopt(d)
        })
    }

    // New show -> adopt the server's option fields and resume row once, like
    // the web App does; polling afterwards must not overwrite local edits.
    function adopt(d) {
        const s = d.session
        const link = s ? (s.link || '') : ''
        if (link !== adoptLink) {
            adoptLink = link
            fields = JSON.parse(JSON.stringify(d.opts.fields || []))
            sel = []
            focusNum = s ? (s.resume !== null ? s.resume
                : (s.episodes.length ? s.episodes[0].num : null)) : null
        } else if (!fields.length && d.opts.fields && d.opts.fields.length) {
            fields = JSON.parse(JSON.stringify(d.opts.fields))
        }
        if (d.log && d.log.length) logLine = d.log[d.log.length - 1]
    }

    function search() {
        const want = q.trim()
        if (!want) return
        api('POST', '/api/search', { q: want }, function (e) { if (e) fail(e) })
    }
    function openRow(row) {
        api('POST', '/api/open', { src: row.source, url: row.url },
            function (e) { if (e) fail(e) })
    }
    function play(eps) {
        if (!eps || !eps.length) return fail('pick at least one episode')
        api('POST', '/api/play', { eps: eps, fields: fields,
            opts: snap.opts.opts || {}, mpv: snap.opts.mpv || [] },
            function (e) { if (e) fail(e) })
    }
    function stop() {
        api('POST', '/api/stop', {}, function (e) { if (e) fail(e) })
    }
    function refresh() {
        api('POST', '/api/settings', { rails: (snap && snap.rails_settings) || {} },
            function (e) { if (e) fail(e) })
    }
    function mark(kind, num, on) {
        api('POST', '/api/watched', { kind: kind, num: num, watched: on },
            function (e) { if (e) fail(e) })
    }
    function fromHere(num) {
        return num ? episodes.filter(function (x) { return x.num >= num })
            .map(function (x) { return x.num }) : episodes.map(function (x) { return x.num })
    }
    function setField(i, patch) {
        const out = fields.slice()
        out[i] = Object.assign({}, out[i], patch)
        fields = out
    }
    function isWatched(num) { return watchedEps.indexOf(num) >= 0 }

    // ---- small pieces ----------------------------------------------------
    component Card: Rectangle {
        color: tk.card
        radius: tk.rEl
        border.width: 1
        border.color: tk.border
    }

    component Btn: Rectangle {
        id: b
        property string label: ''
        property bool primary: false
        signal clicked()
        implicitWidth: lbl.implicitWidth + 20
        implicitHeight: 26
        radius: tk.rIn
        color: primary ? tk.accent : 'transparent'
        border.width: primary ? 0 : 1
        border.color: tk.border
        opacity: enabled ? 1 : 0.45
        Text {
            id: lbl
            anchors.centerIn: parent
            text: b.label
            color: b.primary ? (win.dark ? '#111111' : '#ffffff') : tk.text
            font.family: win.uiFont
            font.pixelSize: tk.xs
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (b.enabled) b.clicked()
        }
    }

    component Chip: Rectangle {
        id: ch
        property string label: ''
        property bool on: false
        signal clicked(int delta)
        implicitWidth: cl.implicitWidth + 16
        implicitHeight: 24
        radius: tk.rIn
        color: ch.on ? tk.muted : 'transparent'
        border.width: 1
        border.color: ch.on ? tk.accent : tk.border
        Text {
            id: cl
            anchors.centerIn: parent
            text: ch.label
            color: tk.text
            font.family: win.uiFont
            font.pixelSize: tk.xs
            opacity: ch.enabled ? 1 : 0.45
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: function (m) { if (ch.enabled) ch.clicked(m.button === Qt.RightButton ? -1 : 1) }
        }
    }

    component TF: TextField {
        color: tk.text
        placeholderTextColor: tk.text2
        font.family: win.uiFont
        font.pixelSize: tk.sm
        padding: 6
        background: Rectangle {
            color: 'transparent'
            radius: tk.rIn
            border.width: 1
            border.color: tk.border
        }
    }

    component MonoText: Text {
        font.family: win.monoFont
        font.pixelSize: tk.xs
        color: tk.text2
    }

    // ---- layout ----------------------------------------------------------
    Shortcut { sequence: '/'; onActivated: searchBox.forceActiveFocus() }
    Shortcut {
        sequence: 'Escape'
        onActivated: { win.q = ''; searchBox.text = ''; win.err = '' }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            // rails: continue watching / recently aired
            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: 232
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8
                    RowLayout {
                        spacing: 6
                        property string tab: 'recent'
                        id: railRow
                        Chip {
                            label: '▶ Continue watching'
                            on: railRow.tab === 'continue'
                            onClicked: railRow.tab = 'continue'
                        }
                        Chip {
                            label: 'Recently aired'
                            on: railRow.tab === 'recent'
                            onClicked: railRow.tab = 'recent'
                        }
                        MonoText {
                            text: (snap && snap.rails ? snap.rails[railRow.tab].length : 0) + ''
                        }
                        Item { Layout.fillWidth: true }
                        MonoText {
                            text: railRow.tab === 'continue' ? 'next unwatched episode'
                                : ((snap && snap.rails_settings && snap.rails_settings.recent
                                    ? snap.rails_settings.recent.days : 14) + ' days')
                        }
                    }
                    ListView {
                        id: railView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        orientation: ListView.Horizontal
                        spacing: 6
                        clip: true
                        model: snap && snap.rails ? snap.rails[railRow.tab] : []
                        delegate: Item {
                            width: 92
                            height: railView.height
                            Column {
                                spacing: 3
                                width: parent.width
                                Rectangle {
                                    width: 92
                                    height: 130
                                    radius: tk.rEl
                                    color: tk.muted
                                    border.width: 1
                                    border.color: tk.border
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        source: modelData.image || ''
                                        fillMode: Image.PreserveAspectCrop
                                        visible: status === Image.Ready
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        visible: !modelData.image
                                        text: (modelData.title || '?').split(/\s+/)
                                            .slice(0, 2).map(function (w) { return (w[0] || '') })
                                            .join('').toUpperCase()
                                        color: tk.text2
                                        font.family: win.uiFont
                                        font.pixelSize: tk.lg
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: modelData.title || ''
                                    elide: Text.ElideRight
                                    color: tk.text
                                    font.family: win.uiFont
                                    font.pixelSize: tk.xs
                                }
                                MonoText {
                                    text: (modelData.days_ago === 0 ? 'today' : modelData.days_ago + 'd ago')
                                        + (modelData.behind ? ' · +' + modelData.behind : '')
                                }
                                Rectangle {
                                    width: parent.width
                                    height: 4
                                    radius: 2
                                    color: tk.muted
                                    Rectangle {
                                        width: parent.width * Math.min(100, Math.max(0, modelData.pct || 0)) / 100
                                        height: 4
                                        radius: 2
                                        color: tk.accent
                                    }
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { win.q = modelData.title; win.search() }
                            }
                        }
                    }
                }
            }

            // search + options
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    TF {
                        id: searchBox
                        Layout.fillWidth: true
                        placeholderText: 'Search or paste a link'
                        text: win.q
                        onTextChanged: win.q = text
                        onAccepted: win.search()
                    }
                    RowLayout {
                        spacing: 8
                        Btn { label: '🔎 Search'; onClicked: win.search() }
                        MonoText {
                            Layout.fillWidth: true
                            text: 'name, link or @channel · Enter searches · / focuses · Esc clears'
                        }
                    }
                }
                // option fields: choice chips cycle (left = back), flags toggle
                Card {
                    Layout.preferredWidth: 470
                    Layout.preferredHeight: 96
                    opacity: win.session ? 1 : 0.55
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        RowLayout {
                            spacing: 6
                            Repeater {
                                model: win.fields.filter(function (f) { return f.kind === 'choice' })
                                delegate: Chip {
                                    property int at: win.fields.indexOf(modelData)
                                    enabled: !!win.session
                                    label: (modelData.label.split(/\s+/)[0]) + ': '
                                        + (modelData.choices[modelData.i] || '')
                                    onClicked: function (delta) {
                                        const f = win.fields[at]
                                        const n = f.choices.length
                                        win.setField(at, { i: ((f.i + delta) % n + n) % n })
                                    }
                                }
                            }
                        }
                        RowLayout {
                            spacing: 6
                            Repeater {
                                model: win.fields.filter(function (f) { return f.kind !== 'choice' && f.kind !== 'text' })
                                delegate: Chip {
                                    property int at: win.fields.indexOf(modelData)
                                    enabled: !!win.session
                                    on: !!modelData.val
                                    label: (modelData.val ? '✓ ' : '') + modelData.label.split(/\s+/)[0]
                                    onClicked: win.setField(at, { val: !win.fields[at].val })
                                }
                            }
                        }
                        RowLayout {
                            spacing: 6
                            Repeater {
                                model: win.fields.filter(function (f) { return f.kind === 'text' })
                                delegate: TF {
                                    property int at: win.fields.indexOf(modelData)
                                    enabled: !!win.session
                                    Layout.preferredWidth: modelData.k === 'cut' ? 96 : 200
                                    placeholderText: modelData.label.split(/\s+/)[0]
                                    text: modelData.val === undefined || modelData.val === null
                                        ? '' : String(modelData.val)
                                    onEditingFinished: win.setField(at, { val: text })
                                }
                            }
                        }
                        MonoText {
                            visible: !win.session
                            text: 'load a show to change these'
                        }
                    }
                }
            }

            // search results
            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: 168
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4
                    RowLayout {
                        MonoText {
                            Layout.fillWidth: true
                            color: tk.text
                            text: !snap ? 'Searching…'
                                : snap.search.busy ? 'Searching…'
                                : snap.search.results.length
                                    ? 'Results · ' + snap.search.results.length + ' for "' + snap.search.q + '"'
                                    : snap.search.q ? 'no hits for "' + snap.search.q + '"' : 'Results · nothing yet'
                        }
                        MonoText { visible: !!snap && snap.search.busy; text: 'busy' }
                    }
                    ListView {
                        id: resultView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: snap ? snap.search.results : []
                        delegate: Item {
                            width: resultView.width
                            height: 26
                            Rectangle {
                                anchors.fill: parent
                                color: ma.containsMouse ? tk.muted : 'transparent'
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                spacing: 8
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    elide: Text.ElideRight
                                    color: tk.text
                                    font.family: win.uiFont
                                    font.pixelSize: tk.sm
                                }
                                MonoText { text: modelData.source || '?' }
                                MonoText {
                                    visible: modelData.matched === 'id'
                                    color: tk.success
                                    text: 'same id'
                                }
                            }
                            MouseArea {
                                id: ma
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: win.openRow(modelData)
                            }
                        }
                    }
                }
            }

            // show + episodes
            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6
                    RowLayout {
                        spacing: 8
                        Text {
                            text: win.session
                                ? win.session.title + ' · ' + win.episodes.length + ' eps'
                                : 'No show loaded'
                            color: tk.text
                            font.family: win.uiFont
                            font.pixelSize: tk.base
                            font.bold: true
                        }
                        MonoText { visible: !!win.session; text: win.session ? win.session.src : '' }
                        MonoText {
                            visible: !!win.session && !!win.session.mal
                            text: win.session && win.session.mal ? 'mal ' + win.session.mal : ''
                        }
                        Item { Layout.fillWidth: true }
                        Btn {
                            label: '▶ Play selected (' + (win.sel.length || 1) + ')'
                            primary: true
                            enabled: win.episodes.length > 0
                            onClicked: win.play(win.sel.length ? win.sel
                                : win.focusNum !== null ? [win.focusNum]
                                : win.episodes.map(function (e) { return e.num }))
                        }
                        Btn {
                            label: '▶ All (' + win.episodes.length + ')'
                            enabled: win.episodes.length > 0
                            onClicked: win.play(win.episodes.map(function (e) { return e.num }))
                        }
                    }
                    MonoText {
                        Layout.fillWidth: true
                        visible: !!win.session && !!win.session.link
                        elide: Text.ElideRight
                        text: win.session ? win.session.link : ''
                    }
                    ListView {
                        id: epView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: win.episodes
                        delegate: Item {
                            width: epView.width
                            height: 26
                            readonly property bool on: win.isWatched(modelData.num)
                            readonly property bool picked: win.sel.indexOf(modelData.num) >= 0
                                || win.focusNum === modelData.num
                            Rectangle {
                                anchors.fill: parent
                                color: picked ? tk.muted : 'transparent'
                                Rectangle {
                                    visible: picked
                                    width: 3
                                    height: parent.height
                                    color: tk.accent
                                }
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                spacing: 8
                                MonoText {
                                    Layout.preferredWidth: 40
                                    color: on ? tk.success : tk.text2
                                    text: (on ? '✓ ' : '') + modelData.num
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.name
                                    elide: Text.ElideRight
                                    color: tk.text
                                    opacity: on ? 0.55 : 1
                                    font.family: win.uiFont
                                    font.pixelSize: tk.sm
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                cursorShape: Qt.PointingHandCursor
                                onClicked: function (m) {
                                    win.focusNum = modelData.num
                                    win.sel = [modelData.num]
                                    if (m.button === Qt.RightButton) {
                                        epMenu.num = modelData.num
                                        epMenu.popup()
                                    }
                                }
                                onDoubleClicked: win.play(win.fromHere(modelData.num))
                            }
                        }
                    }
                    MonoText {
                        visible: !win.session
                        text: 'search a title and click a result — the episode list and the '
                            + 'controls above stay in place and activate for it'
                    }
                }
            }

            // status strip
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Btn {
                    label: '■ Stop'
                    enabled: !!win.session
                    onClicked: win.stop()
                }
                MonoText { text: win.status }
                MonoText {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: win.logLine
                }
                Btn { label: 'Close'; onClicked: Qt.quit() }
            }
        }

        // sidebar: agenda, history
        ColumnLayout {
            Layout.preferredWidth: 340
            Layout.fillHeight: true
            spacing: 8

            RowLayout {
                spacing: 6
                Repeater {
                    model: [['simkl', 'Simkl'], ['gate', 'AnimeGate'], ['anilist', 'AniList']]
                    delegate: MonoText {
                        color: !snap || !snap.lights ? tk.text2
                            : snap.lights[modelData[0]] === 'ok' ? tk.success
                            : snap.lights[modelData[0]] === 'warn' ? tk.info
                            : snap.lights[modelData[0]] === 'bad' ? tk.error : tk.text2
                        text: '● ' + modelData[1]
                    }
                }
                Item { Layout.fillWidth: true }
                Btn { label: '↻'; onClicked: win.refresh() }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4
                    RowLayout {
                        spacing: 6
                        property string tab: 'all'
                        id: feedRow
                        Chip {
                            label: '14 days ' + win.agenda().length
                            on: feedRow.tab === 'all'
                            onClicked: feedRow.tab = 'all'
                        }
                        Chip {
                            label: 'Aired ' + (snap ? snap.feed.length : 0)
                            on: feedRow.tab === 'aired'
                            onClicked: feedRow.tab = 'aired'
                        }
                        Chip {
                            label: 'Upcoming ' + (snap ? snap.upcoming.length : 0)
                            on: feedRow.tab === 'upcoming'
                            onClicked: feedRow.tab = 'upcoming'
                        }
                    }
                    ListView {
                        id: feedView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: feedRow.tab === 'all' ? win.agenda()
                            : feedRow.tab === 'aired' ? (snap ? snap.feed : [])
                            : (snap ? snap.upcoming : [])
                        delegate: Item {
                            width: feedView.width
                            height: 24
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                spacing: 8
                                MonoText {
                                    Layout.preferredWidth: 56
                                    text: modelData.days === undefined
                                        ? String(modelData.date || '').slice(5)
                                        : (modelData.days === 0 ? 'today' : modelData.days + 'd')
                                }
                                MonoText {
                                    Layout.preferredWidth: 40
                                    text: modelData.ep === undefined ? '' : String(modelData.ep)
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title || ''
                                    elide: Text.ElideRight
                                    color: tk.text
                                    font.family: win.uiFont
                                    font.pixelSize: tk.xs
                                }
                                MonoText { visible: !!modelData.new; color: tk.success; text: 'new' }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { win.q = modelData.title; win.search() }
                            }
                        }
                    }
                    MonoText {
                        visible: feedView.count === 0
                        text: feedRow.tab === 'upcoming'
                            ? 'no scheduled episodes — refresh the feed ↻'
                            : 'nothing aired in the last 14 days — widen the days in ⚙ settings'
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: 170
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4
                    MonoText { text: 'History'; color: tk.text }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: snap ? snap.history : []
                        delegate: Item {
                            width: parent ? parent.width : 0
                            height: 22
                            RowLayout {
                                anchors.fill: parent
                                spacing: 8
                                MonoText { Layout.preferredWidth: 80; elide: Text.ElideRight; text: modelData.watched || '' }
                                MonoText { Layout.preferredWidth: 44; text: modelData.prog || '' }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title || ''
                                    elide: Text.ElideRight
                                    color: tk.text
                                    font.family: win.uiFont
                                    font.pixelSize: tk.xs
                                }
                            }
                        }
                    }
                }
            }
            Btn { label: '↻ refresh feed & history'; onClicked: win.refresh() }
        }
    }

    // one agenda: just aired first, then what is coming (same order as the web)
    function agenda() {
        if (!snap) return []
        const soon = snap.upcoming.slice().sort(function (a, b) {
            return String(a.date).localeCompare(String(b.date))
        })
        return snap.feed.concat(soon)
    }

    // per-episode actions (the web shows these in a ⋯ dropdown)
    Menu {
        id: epMenu
        property int num: 0
        MenuItem {
            text: win.isWatched(epMenu.num) ? '✓ Mark unwatched' : 'Mark watched'
            onTriggered: win.mark('episode', epMenu.num)
        }
        MenuItem { text: 'Mark watched up to here'; onTriggered: win.mark('till_here', epMenu.num) }
        MenuItem { text: 'Mark whole season watched'; onTriggered: win.mark('season', epMenu.num, true) }
        MenuItem { text: 'Mark season unwatched'; onTriggered: win.mark('season', epMenu.num, false) }
        MenuItem {
            text: win.session && win.session.watched && win.session.watched.complete
                ? '✓ Unmark complete' : 'Mark series complete'
            onTriggered: win.mark('series', epMenu.num)
        }
        MenuSeparator {}
        MenuItem { text: '▶ Play from here to the end'; onTriggered: win.play(win.fromHere(epMenu.num)) }
        MenuItem { text: '▶ Play only selected'; onTriggered: win.play([epMenu.num]) }
        MenuItem { text: '▶ Play all'; onTriggered: win.play(win.episodes.map(function (e) { return e.num })) }
    }
}
