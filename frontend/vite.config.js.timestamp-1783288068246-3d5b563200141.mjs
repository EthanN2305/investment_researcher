// vite.config.js
import { defineConfig } from "file:///sessions/relaxed-vigilant-fermi/mnt/Agentic%20AI%20Investment%20Project/frontend/node_modules/vite/dist/node/index.js";
import react from "file:///sessions/relaxed-vigilant-fermi/mnt/Agentic%20AI%20Investment%20Project/frontend/node_modules/@vitejs/plugin-react/dist/index.js";
var vite_config_default = defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/research": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/portfolio": "http://localhost:8000",
      "/preferences": "http://localhost:8000",
      "/watchlist": "http://localhost:8000",
      "/summaries": "http://localhost:8000",
      "/alerts": "http://localhost:8000",
      "/notifications": "http://localhost:8000",
      "/digest": "http://localhost:8000",
      "/recommendations": "http://localhost:8000",
      "/learn": "http://localhost:8000"
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcuanMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvc2Vzc2lvbnMvcmVsYXhlZC12aWdpbGFudC1mZXJtaS9tbnQvQWdlbnRpYyBBSSBJbnZlc3RtZW50IFByb2plY3QvZnJvbnRlbmRcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIi9zZXNzaW9ucy9yZWxheGVkLXZpZ2lsYW50LWZlcm1pL21udC9BZ2VudGljIEFJIEludmVzdG1lbnQgUHJvamVjdC9mcm9udGVuZC92aXRlLmNvbmZpZy5qc1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vc2Vzc2lvbnMvcmVsYXhlZC12aWdpbGFudC1mZXJtaS9tbnQvQWdlbnRpYyUyMEFJJTIwSW52ZXN0bWVudCUyMFByb2plY3QvZnJvbnRlbmQvdml0ZS5jb25maWcuanNcIjtpbXBvcnQgeyBkZWZpbmVDb25maWcgfSBmcm9tIFwidml0ZVwiO1xuaW1wb3J0IHJlYWN0IGZyb20gXCJAdml0ZWpzL3BsdWdpbi1yZWFjdFwiO1xuXG4vLyBEZXYgc2VydmVyIHByb3hpZXMgQVBJIHBhdGhzIHRvIHRoZSBGYXN0QVBJIGJhY2tlbmQgc28gdGhlIGZyb250ZW5kIGNhblxuLy8gY2FsbCBzYW1lLW9yaWdpbiBwYXRocyBkdXJpbmcgZGV2ZWxvcG1lbnQuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbcmVhY3QoKV0sXG4gIHNlcnZlcjoge1xuICAgIHBvcnQ6IDUxNzMsXG4gICAgcHJveHk6IHtcbiAgICAgIFwiL3Jlc2VhcmNoXCI6IFwiaHR0cDovL2xvY2FsaG9zdDo4MDAwXCIsXG4gICAgICBcIi9oZWFsdGhcIjogXCJodHRwOi8vbG9jYWxob3N0OjgwMDBcIixcbiAgICAgIFwiL2F1dGhcIjogXCJodHRwOi8vbG9jYWxob3N0OjgwMDBcIixcbiAgICAgIFwiL3BvcnRmb2xpb1wiOiBcImh0dHA6Ly9sb2NhbGhvc3Q6ODAwMFwiLFxuICAgICAgXCIvcHJlZmVyZW5jZXNcIjogXCJodHRwOi8vbG9jYWxob3N0OjgwMDBcIixcbiAgICAgIFwiL3dhdGNobGlzdFwiOiBcImh0dHA6Ly9sb2NhbGhvc3Q6ODAwMFwiLFxuICAgICAgXCIvc3VtbWFyaWVzXCI6IFwiaHR0cDovL2xvY2FsaG9zdDo4MDAwXCIsXG4gICAgICBcIi9hbGVydHNcIjogXCJodHRwOi8vbG9jYWxob3N0OjgwMDBcIixcbiAgICAgIFwiL25vdGlmaWNhdGlvbnNcIjogXCJodHRwOi8vbG9jYWxob3N0OjgwMDBcIixcbiAgICAgIFwiL2RpZ2VzdFwiOiBcImh0dHA6Ly9sb2NhbGhvc3Q6ODAwMFwiLFxuICAgICAgXCIvcmVjb21tZW5kYXRpb25zXCI6IFwiaHR0cDovL2xvY2FsaG9zdDo4MDAwXCIsXG4gICAgICBcIi9sZWFyblwiOiBcImh0dHA6Ly9sb2NhbGhvc3Q6ODAwMFwiLFxuICAgIH0sXG4gIH0sXG59KTtcbiJdLAogICJtYXBwaW5ncyI6ICI7QUFBeVosU0FBUyxvQkFBb0I7QUFDdGIsT0FBTyxXQUFXO0FBSWxCLElBQU8sc0JBQVEsYUFBYTtBQUFBLEVBQzFCLFNBQVMsQ0FBQyxNQUFNLENBQUM7QUFBQSxFQUNqQixRQUFRO0FBQUEsSUFDTixNQUFNO0FBQUEsSUFDTixPQUFPO0FBQUEsTUFDTCxhQUFhO0FBQUEsTUFDYixXQUFXO0FBQUEsTUFDWCxTQUFTO0FBQUEsTUFDVCxjQUFjO0FBQUEsTUFDZCxnQkFBZ0I7QUFBQSxNQUNoQixjQUFjO0FBQUEsTUFDZCxjQUFjO0FBQUEsTUFDZCxXQUFXO0FBQUEsTUFDWCxrQkFBa0I7QUFBQSxNQUNsQixXQUFXO0FBQUEsTUFDWCxvQkFBb0I7QUFBQSxNQUNwQixVQUFVO0FBQUEsSUFDWjtBQUFBLEVBQ0Y7QUFDRixDQUFDOyIsCiAgIm5hbWVzIjogW10KfQo=
