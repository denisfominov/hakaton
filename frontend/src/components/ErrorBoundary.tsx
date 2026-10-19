import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface State {
  error: Error | null;
}

// без этого любая ошибка рендера даёт пустой белый экран
export default class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error:", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // при переходе на другую страницу пробуем отрисовать заново
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <p className="text-lg font-semibold">Что-то пошло не так при отображении страницы</p>
        <p className="mt-2 text-sm text-ink-500">{this.state.error.message}</p>
        <button className="btn-primary mt-5" onClick={() => window.location.reload()}>Обновить страницу</button>
      </div>
    );
  }
}
