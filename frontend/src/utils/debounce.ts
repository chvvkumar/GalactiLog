/**
 * Creates a debounced version of a callback.
 * Returns a function that delays invoking `fn` until after `delay` ms
 * have elapsed since the last invocation.
 */
export function debounce<T extends (...args: any[]) => void>(fn: T, delay: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  }) as T;
}
