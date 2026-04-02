import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider } from './lib/theme'
import GlobalErrorBoundary from './components/GlobalErrorBoundary'
import { ToastProvider } from './components/ToastProvider'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <GlobalErrorBoundary>
      <ThemeProvider>
        <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <ToastProvider>
            <App />
          </ToastProvider>
        </BrowserRouter>
      </ThemeProvider>
    </GlobalErrorBoundary>
  </React.StrictMode>
)
