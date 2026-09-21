(function () {
  var WORKSPACE_MODES = ["prep", "run", "review"];

  function draftKey(campaignId, formName, fieldName) {
    return "campaign-" + campaignId + "-" + formName + "-" + fieldName;
  }

  function clearFormDrafts(form) {
    var campaignId = form.dataset.campaignId;
    var formName = form.dataset.draftForm;
    if (!campaignId || !formName) return;
    form.querySelectorAll("[name]").forEach(function (field) {
      if (!field.name) return;
      localStorage.removeItem(draftKey(campaignId, formName, field.name));
    });
  }

  function restoreFormDrafts(form) {
    var campaignId = form.dataset.campaignId;
    var formName = form.dataset.draftForm;
    if (!campaignId || !formName) return;
    form.querySelectorAll("[name]").forEach(function (field) {
      if (!field.name) return;
      var saved = localStorage.getItem(draftKey(campaignId, formName, field.name));
      if (saved !== null && field.value === "") {
        field.value = saved;
      }
    });
  }

  function restoreAllDrafts() {
    document.querySelectorAll("form[data-draft-form]").forEach(restoreFormDrafts);
  }

  function setCookie(name, value, days) {
    var expires = "";
    if (days) {
      var date = new Date();
      date.setTime(date.getTime() + days * 86400000);
      expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + encodeURIComponent(value) + expires + "; path=/; SameSite=Lax";
  }

  function persistCampaign(campaignId) {
    if (!campaignId) return;
    localStorage.setItem("mc:last_campaign_id", String(campaignId));
    setCookie("mc_last_campaign_id", String(campaignId), 365);
  }

  function persistSession(campaignId, sessionId, mode) {
    if (!campaignId) return;
    persistCampaign(campaignId);
    if (sessionId) {
      localStorage.setItem("mc:last_session:" + campaignId, String(sessionId));
      setCookie("mc_session_" + campaignId, String(sessionId), 365);
    }
    if (mode && WORKSPACE_MODES.indexOf(mode) !== -1) {
      localStorage.setItem("mc:last_mode:" + campaignId, mode);
      setCookie("mc_mode_" + campaignId, mode, 365);
    }
  }

  function workspaceUrl(campaignId, sessionId, mode) {
    var url = "/campaigns/" + campaignId + "/workspace";
    var params = [];
    if (sessionId) params.push("session_id=" + encodeURIComponent(sessionId));
    if (mode && WORKSPACE_MODES.indexOf(mode) !== -1) params.push("mode=" + encodeURIComponent(mode));
    if (params.length) url += "?" + params.join("&");
    return url;
  }

  function persistSessionOnly(campaignId, sessionId) {
    if (!campaignId || !sessionId) return;
    persistCampaign(campaignId);
    localStorage.setItem("mc:last_session:" + campaignId, String(sessionId));
    setCookie("mc_session_" + campaignId, String(sessionId), 365);
  }

  function initPersistence() {
    var body = document.body;
    if (!body) return;
    var campaignId = body.dataset.mcCampaignId;
    var sessionId = body.dataset.mcSessionId;
    var mode = body.dataset.mcMode;
    var layout = body.dataset.mcLayout;
    if (!campaignId) return;
    persistCampaign(campaignId);
    if (layout === "workspace") {
      persistSession(campaignId, sessionId, mode || "prep");
    } else if (sessionId) {
      persistSessionOnly(campaignId, sessionId);
    }
  }

  function initCampaignSelect() {
    var select = document.querySelector(".mc-campaign-select");
    if (!select) return;
    select.addEventListener("change", function () {
      if (!select.value) return;
      var campaignId = select.value;
      var sessionId = localStorage.getItem("mc:last_session:" + campaignId);
      var mode = localStorage.getItem("mc:last_mode:" + campaignId) || "prep";
      window.location.href = workspaceUrl(campaignId, sessionId, mode);
    });
  }

  function initSidebarDrawer() {
    var toggle = document.querySelector(".mc-sidebar-toggle");
    var backdrop = document.querySelector("[data-mc-sidebar-backdrop]");
    if (!toggle || !backdrop) return;

    function setOpen(open) {
      document.body.classList.toggle("sidebar-drawer-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      backdrop.hidden = !open;
    }

    toggle.addEventListener("click", function () {
      setOpen(!document.body.classList.contains("sidebar-drawer-open"));
    });

    backdrop.addEventListener("click", function () {
      setOpen(false);
    });

    document.querySelectorAll(".mc-sidebar a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.matchMedia("(max-width: 768px)").matches) {
          setOpen(false);
        }
      });
    });
  }

  function initContinueCard() {
    var card = document.getElementById("mc-continue-card");
    var label = document.getElementById("mc-continue-label");
    var workspaceLink = document.getElementById("mc-continue-workspace");
    var loreBoardLink = document.getElementById("mc-continue-lore-board");
    var indexEl = document.getElementById("mc-campaign-index");
    if (!card || !label || !workspaceLink || !loreBoardLink || !indexEl) return;

    var campaignId = localStorage.getItem("mc:last_campaign_id");
    if (!campaignId) return;

    var campaigns;
    try {
      campaigns = JSON.parse(indexEl.textContent || "[]");
    } catch (err) {
      return;
    }

    var match = campaigns.find(function (entry) {
      return String(entry.id) === String(campaignId);
    });
    if (!match) return;

    var sessionId = localStorage.getItem("mc:last_session:" + campaignId);
    var mode = localStorage.getItem("mc:last_mode:" + campaignId) || "prep";
    var sessionLabel = sessionId ? " · Session " + sessionId + " · " + mode + " mode" : "";
    label.textContent = match.name + sessionLabel;
    workspaceLink.href = workspaceUrl(campaignId, sessionId, mode);
    loreBoardLink.href = "/campaigns/" + campaignId;
    card.hidden = false;
  }

  function appendReturnTo(url, returnTo) {
    if (!returnTo || returnTo.indexOf("/") !== 0 || returnTo.indexOf("//") === 0) return url;
    var sep = url.indexOf("?") === -1 ? "?" : "&";
    return url + sep + "return_to=" + encodeURIComponent(returnTo);
  }

  window.mcAppendReturnTo = appendReturnTo;
  window.mcWorkspaceUrl = workspaceUrl;

  document.body.addEventListener("input", function (event) {
    var field = event.target;
    if (!field.name) return;
    var form = field.closest("form[data-draft-form]");
    if (!form) return;
    var campaignId = form.dataset.campaignId;
    var formName = form.dataset.draftForm;
    if (!campaignId || !formName) return;
    localStorage.setItem(draftKey(campaignId, formName, field.name), field.value);
  });

  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (!event.detail.successful) return;
    var elt = event.detail.elt;
    if (elt && elt.tagName === "FORM" && elt.dataset.draftForm) {
      clearFormDrafts(elt);
    }
  });

  document.body.addEventListener("htmx:afterSwap", restoreAllDrafts);

  function initWorkspaceDirtyState() {
    var textarea = document.querySelector("[data-workspace-editor]");
    var status = document.getElementById("mc-workspace-save-status");
    if (!textarea || !status) return;

    var savedValue = textarea.value;
    var dirty = false;

    function setState(isDirty) {
      dirty = isDirty;
      status.dataset.state = isDirty ? "dirty" : "saved";
      status.textContent = isDirty ? "Unsaved changes" : "Saved";
      status.classList.toggle("is-dirty", isDirty);
    }

    textarea.addEventListener("input", function () {
      setState(textarea.value !== savedValue);
    });

    textarea.closest("form").addEventListener("submit", function () {
      savedValue = textarea.value;
      setState(false);
    });

    window.addEventListener("beforeunload", function (event) {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  function toggleConditionalReveal(control) {
    if (!control || !control.getAttribute) return;
    var targetName = control.getAttribute("data-mc-reveals");
    if (!targetName) return;
    var revealValue = control.getAttribute("data-mc-reveals-value") || "other";
    var container = control.closest("form") || control.closest(".card-body") || control.parentElement;
    if (!container) return;
    var target = container.querySelector('[data-mc-reveal-target="' + targetName + '"]');
    if (!target) return;
    target.hidden = control.value !== revealValue;
  }

  function initConditionalRevealFields(root) {
    var scope = root || document;
    scope.querySelectorAll("select[data-mc-reveals], input[type='hidden'][data-mc-reveals]").forEach(toggleConditionalReveal);
  }

  function initMultiselectCombobox(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-mc-multiselect]").forEach(function (widget) {
      if (widget.dataset.mcMultiselectReady) return;
      widget.dataset.mcMultiselectReady = "1";

      var fieldName = widget.getAttribute("data-field-name");
      var tagsEl = widget.querySelector(".mc-multiselect-tags");
      var searchInput = widget.querySelector(".mc-multiselect-search");
      var dropdown = widget.querySelector(".mc-multiselect-dropdown");
      var valuesEl = widget.querySelector(".mc-multiselect-values");
      if (!fieldName || !tagsEl || !searchInput || !dropdown || !valuesEl) return;

      function selectedValues() {
        var values = {};
        valuesEl.querySelectorAll('input[type="hidden"]').forEach(function (input) {
          values[input.value] = true;
        });
        return values;
      }

      function syncOptionVisibility() {
        var selected = selectedValues();
        dropdown.querySelectorAll(".mc-multiselect-option").forEach(function (option) {
          var isSelected = !!selected[option.getAttribute("data-value")];
          option.classList.toggle("is-selected", isSelected);
          option.hidden = isSelected;
        });
      }

      function addSelection(value, label) {
        if (!value || selectedValues()[value]) return;
        var tag = document.createElement("span");
        tag.className = "mc-multiselect-tag";
        tag.setAttribute("data-value", value);
        tag.innerHTML =
          '<span class="mc-multiselect-tag-label"></span>' +
          '<button type="button" class="mc-multiselect-tag-remove" aria-label="Remove ' +
          label.replace(/"/g, "") +
          '">&times;</button>';
        tag.querySelector(".mc-multiselect-tag-label").textContent = label;

        var hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = fieldName;
        hidden.value = value;

        tagsEl.appendChild(tag);
        valuesEl.appendChild(hidden);
        syncOptionVisibility();
        searchInput.value = "";
        filterOptions("");
      }

      function removeSelection(value) {
        var tag = tagsEl.querySelector('.mc-multiselect-tag[data-value="' + value + '"]');
        var hidden = valuesEl.querySelector('input[type="hidden"][value="' + value + '"]');
        if (tag) tag.remove();
        if (hidden) hidden.remove();
        syncOptionVisibility();
      }

      function filterOptions(query) {
        var needle = (query || "").trim().toLowerCase();
        dropdown.querySelectorAll(".mc-multiselect-option").forEach(function (option) {
          if (option.hidden) return;
          var label = (option.getAttribute("data-label") || option.textContent || "").toLowerCase();
          option.classList.toggle("is-filtered-out", needle && label.indexOf(needle) === -1);
        });
      }

      function openDropdown() {
        dropdown.hidden = false;
        filterOptions(searchInput.value);
      }

      function closeDropdown() {
        dropdown.hidden = true;
      }

      searchInput.addEventListener("focus", openDropdown);
      searchInput.addEventListener("input", function () {
        openDropdown();
        filterOptions(searchInput.value);
      });

      dropdown.addEventListener("click", function (event) {
        var option = event.target.closest(".mc-multiselect-option");
        if (!option || option.hidden) return;
        addSelection(option.getAttribute("data-value"), option.getAttribute("data-label") || option.textContent.trim());
        searchInput.focus();
      });

      tagsEl.addEventListener("click", function (event) {
        var button = event.target.closest(".mc-multiselect-tag-remove");
        if (!button) return;
        var tag = button.closest(".mc-multiselect-tag");
        if (!tag) return;
        removeSelection(tag.getAttribute("data-value"));
      });

      document.addEventListener("click", function (event) {
        if (!widget.contains(event.target)) closeDropdown();
      });

      syncOptionVisibility();
    });
  }

  function initSearchableSelects(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-mc-searchable-select]").forEach(function (widget) {
      if (widget.dataset.mcSearchableReady) return;
      widget.dataset.mcSearchableReady = "1";

      var hiddenInput = widget.querySelector('input[type="hidden"]');
      var displayInput = widget.querySelector(".mc-searchable-select-display");
      var list = widget.querySelector(".mc-searchable-select-list");
      if (!hiddenInput || !displayInput || !list) return;

      function setValue(value, label) {
        hiddenInput.value = value || "";
        displayInput.value = label || "";
        toggleConditionalReveal(hiddenInput);
        list.hidden = true;
        displayInput.setAttribute("aria-expanded", "false");
      }

      function filterOptions(query) {
        var needle = (query || "").trim().toLowerCase();
        list.querySelectorAll(".mc-searchable-select-option").forEach(function (option) {
          var label = (option.getAttribute("data-label") || option.textContent || "").toLowerCase();
          var item = option.closest("li");
          if (!item) return;
          item.hidden = needle && label.indexOf(needle) === -1;
        });
      }

      function openList() {
        list.hidden = false;
        displayInput.setAttribute("aria-expanded", "true");
        filterOptions(displayInput.value);
      }

      displayInput.addEventListener("focus", openList);
      displayInput.addEventListener("input", function () {
        openList();
        filterOptions(displayInput.value);
        if (!displayInput.value.trim()) {
          hiddenInput.value = "";
          toggleConditionalReveal(hiddenInput);
        }
      });

      list.addEventListener("click", function (event) {
        var option = event.target.closest(".mc-searchable-select-option");
        if (!option) return;
        setValue(option.getAttribute("data-value"), option.getAttribute("data-label") || option.textContent.trim());
      });

      document.addEventListener("click", function (event) {
        if (!widget.contains(event.target)) {
          list.hidden = true;
          displayInput.setAttribute("aria-expanded", "false");
        }
      });

      toggleConditionalReveal(hiddenInput);
    });
  }

  document.body.addEventListener("change", function (event) {
    var control = event.target;
    if (
      control &&
      control.matches &&
      (control.matches("select[data-mc-reveals]") || control.matches("input[type='hidden'][data-mc-reveals]"))
    ) {
      toggleConditionalReveal(control);
    }
  });

  document.body.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form || form.tagName !== "FORM") return;
      form.querySelectorAll("[data-mc-reveal-target][hidden]").forEach(function (target) {
        target.hidden = false;
      });
    },
    true
  );

  function initQuickRulesReference() {
    var section = document.querySelector("[data-mc-quick-rules]");
    if (!section) return;

    var campaignId = section.getAttribute("data-campaign-id");
    var toggle = section.querySelector("[data-mc-quick-rules-toggle]");
    var drawer = section.querySelector("[data-mc-quick-rules-drawer]");
    var resultsEl = section.querySelector("[data-mc-quick-rules-results]");
    var statusEl = section.querySelector("[data-mc-quick-rules-status]");
    if (!campaignId || !resultsEl) return;

    if (toggle && drawer) {
      toggle.addEventListener("click", function () {
        var open = !section.classList.contains("is-open");
        section.classList.toggle("is-open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    var debounceTimer = null;
    var lastFetchKey = "";
    var activeRequest = 0;

    function sourceTextFromElement(el) {
      if (!el) return "";
      if (el.matches("[data-rules-lookup-text]")) {
        return (el.getAttribute("data-rules-lookup-text") || "").trim();
      }
      if (el.matches("input, textarea, select")) {
        return (el.value || "").trim();
      }
      return (el.textContent || "").trim();
    }

    function collectSourceText() {
      var parts = [];
      document.querySelectorAll("[data-rules-lookup-source], [data-rules-lookup-text]").forEach(function (el) {
        var text = sourceTextFromElement(el);
        if (text) parts.push(text);
      });
      return parts.join("\n\n");
    }

    function setStatus(message) {
      if (statusEl) statusEl.textContent = message;
    }

    function renderResults(snippets) {
      if (!snippets.length) {
        resultsEl.innerHTML = "";
        setStatus("No matching rules found.");
        return;
      }

      fetch("/api/workspace/render-markdown", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snippets: snippets }),
      })
        .then(function (response) {
          if (!response.ok) throw new Error("render failed");
          return response.json();
        })
        .then(function (data) {
          var html = data.html || [];
          resultsEl.innerHTML = html
            .map(function (fragment) {
              return '<article class="mc-quick-rules-card markdown-body">' + fragment + "</article>";
            })
            .join("");
          setStatus(
            snippets.length + " matching rule" + (snippets.length === 1 ? "" : "s")
          );
        })
        .catch(function () {
          resultsEl.innerHTML = "";
          setStatus("Could not render rule snippets.");
        });
    }

    function runLookup() {
      var text = collectSourceText();
      if (!text.trim()) {
        resultsEl.innerHTML = "";
        setStatus("Type in the workspace to surface matching rules.");
        lastFetchKey = "";
        return;
      }
      if (text === lastFetchKey) return;
      lastFetchKey = text;

      var requestId = ++activeRequest;
      setStatus("Looking up rules…");

      var url =
        "/api/workspace/rules-lookup?campaign_id=" +
        encodeURIComponent(campaignId) +
        "&text=" +
        encodeURIComponent(text);

      fetch(url)
        .then(function (response) {
          if (!response.ok) throw new Error("lookup failed");
          return response.json();
        })
        .then(function (snippets) {
          if (requestId !== activeRequest) return;
          renderResults(Array.isArray(snippets) ? snippets : []);
        })
        .catch(function () {
          if (requestId !== activeRequest) return;
          resultsEl.innerHTML = "";
          setStatus("Rules lookup failed.");
        });
    }

    function scheduleLookup() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runLookup, 400);
    }

    function bindSourceListeners(root) {
      var scope = root || document;
      scope.querySelectorAll("[data-rules-lookup-source]").forEach(function (el) {
        if (el.dataset.mcRulesLookupBound) return;
        el.dataset.mcRulesLookupBound = "1";
        el.addEventListener("input", scheduleLookup);
        el.addEventListener("change", scheduleLookup);
      });
    }

    bindSourceListeners();

    document.querySelectorAll("[data-rules-lookup-watch]").forEach(function (watchRoot) {
      var observer = new MutationObserver(scheduleLookup);
      observer.observe(watchRoot, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: ["data-rules-lookup-text", "value"],
      });
    });

    runLookup();
  }

  document.addEventListener("DOMContentLoaded", function () {
    restoreAllDrafts();
    initPersistence();
    initCampaignSelect();
    initSidebarDrawer();
    initContinueCard();
    initWorkspaceDirtyState();
    initConditionalRevealFields();
    initMultiselectCombobox();
    initSearchableSelects();
    initQuickRulesReference();
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    initConditionalRevealFields(event.detail.target);
    initMultiselectCombobox(event.detail.target);
    initSearchableSelects(event.detail.target);
  });
})();
