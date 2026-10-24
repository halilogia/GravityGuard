import * as net from 'net';

export const MAX_ROUTER_RESPONSE_BYTES = 2 * 1024 * 1024;

export function routerEndpoint(host: string, port: number): { hostname: string; port: number; protocol: 'http:' | 'https:' } {
  const url = host.includes('://') ? new URL(host) : new URL(`http://${host.includes(':') && !host.startsWith('[') ? `[${host}]` : host}:${port}`);
  const hostname = url.hostname.replace(/^\[|\]$/g, '');
  const loopback = hostname === 'localhost' || hostname === '::1' || (net.isIP(hostname) === 4 && hostname.startsWith('127.'));
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash || !['http:', 'https:'].includes(url.protocol)) {
    throw new Error('Invalid router endpoint');
  }
  if (url.protocol === 'http:' && !loopback) throw new Error('Remote router endpoints require HTTPS');
  const selectedPort = url.port ? Number(url.port) : url.protocol === 'https:' ? 443 : 80;
  if (!Number.isSafeInteger(selectedPort) || selectedPort < 1 || selectedPort > 65535) throw new Error('Invalid router port');
  return { hostname, port: selectedPort, protocol: url.protocol as 'http:' | 'https:' };
}
