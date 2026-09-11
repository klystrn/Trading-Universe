/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // three ships untranspiled ESM examples; Next needs to compile them.
  transpilePackages: ["three"],
  async rewrites() {
    // Proxy the API in development so the browser sees a single origin and the
    // WebSocket does not trip CORS.
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
