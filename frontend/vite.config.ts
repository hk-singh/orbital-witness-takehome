import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [react()],
	server: {
		port: 5173,
		host: "0.0.0.0",
		// Allow the dev server to be reached through forwarded/tunneled hosts
		// (e.g. GitHub Codespaces' *.app.github.dev URLs). Without this, Vite 6
		// rejects them with "Blocked request. This host is not allowed."
		allowedHosts: [".app.github.dev", ".githubpreview.dev", "localhost"],
		proxy: {
			"/api": {
				target: "http://backend:8000",
				changeOrigin: true,
			},
		},
	},
});
