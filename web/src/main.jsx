import { createRoot } from 'react-dom/client'
import { Theme } from '@astryxdesign/core'
import { neutralTheme } from '@astryxdesign/theme-neutral'

import '@astryxdesign/core/reset.css'
import '@astryxdesign/core/astryx.css'
import '@astryxdesign/theme-neutral/theme.css'
import './styles.css'

import App from './app.jsx'

createRoot(document.getElementById('root')).render(
  <Theme theme={neutralTheme} mode="dark">
    <App />
  </Theme>,
)
