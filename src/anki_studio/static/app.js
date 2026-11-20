// Small interface states of Anki Studio (Alpine.js). No business logic:
// the server checks every value again.
document.addEventListener("alpine:init", () => {
  // Generation form: which options are visible and whether content leaves
  // the server. The effective PDF mode per profile comes from the server.
  window.Alpine.data("generateForm", () => ({
    profile: "",
    pdfMode: "",
    pictureBackend: "",
    target: "new_apkg",
    profileModes: {},
    defaultBackend: "local",

    init() {
      const data = this.$el.dataset;
      this.profileModes = JSON.parse(data.profileModes || "{}");
      this.defaultBackend = data.defaultBackend || "local";
      this.profile = data.profile || "";
      this.pdfMode = data.pdfMode || "";
      this.pictureBackend = data.pictureBackend || "";
      this.target = data.target || "new_apkg";
    },

    get effectiveMode() {
      return this.pdfMode || this.profileModes[this.profile] || this.profileModes[""] || "local";
    },

    get structured() {
      return this.effectiveMode === "structured";
    },

    get transfer() {
      const backend = this.pictureBackend || this.defaultBackend;
      return this.effectiveMode === "native" || (this.structured && backend === "profile");
    },

    get extend() {
      return this.target === "extend_apkg";
    },
  }));
});
