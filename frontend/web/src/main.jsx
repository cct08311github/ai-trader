import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider } from './lib/theme'
import GlobalErrorBoundary from './components/GlobalErrorBoundary'
import { ToastProvider } from './components/ToastProvider'
import FloatingLogout from './components/FloatingLogout'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <GlobalErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
          <ToastProvider>
            <App />
            {/* FloatingLogout is OUTSIDE routing so it always renders on every page */}
            <FloatingLogout />
          </ToastProvider>
        </BrowserRouter>
      </ThemeProvider>
    </GlobalErrorBoundary>
  </React.StrictMode>
)
