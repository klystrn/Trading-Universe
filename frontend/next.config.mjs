/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
// STATIC_EXPORT=1 produces a plain static site in out/ that the FastAPI backend
// serves itself, so one process is the whole deployment.
const isExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  // three ships untranspiled ESM examples; Next needs to compile them.
  transpilePackages: ["three"],
  images: { unoptimized: true },
  ...(isExport
    ? { output: "export" }
    : {
        async rewrites() {
          // Proxy the API in development so the browser sees a single origin
          // and the WebSocket does not trip CORS.
          return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
        },
      }),
};

export default nextConfig;
