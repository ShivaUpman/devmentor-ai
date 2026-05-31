/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output makes the Docker image smaller and self-contained
  // output: 'standalone',  // Uncomment for production Docker builds
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost/api',
  },
  // Suppress the "version" warning that appears with older Next.js
  experimental: {},
}

module.exports = nextConfig
