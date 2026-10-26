/**
 * TORUS Clinical Notifications, Two-Way Chat & AI Support System
 * PlebC TORUS - Tele Operated Robotic Ultrasound System
 */

(function () {
  "use strict";

  // State
  let activeNotifications = [];
  let unreadNotifCount = 0;
  let activeConversations = [];
  let currentActiveConvId = null;
  let chatPollTimer = null;
  let notifPollTimer = null;
  let isChatDrawerOpen = false;
  let isSendingMessage = false;
  let isAiQuerying = false;

  // Helper: Get authenticated user details
  function getTorusUser() {
    const isDoc = (window.currentAuthenticatedUser && window.currentAuthenticatedUser.role === "doctor") ||
      (window.currentAuthenticatedRole === "doctor") ||
      (document.getElementById("role") && document.getElementById("role").value === "doctor") ||
      (document.getElementById("docDashAvatarChip") && document.getElementById("docDashAvatarChip").textContent.trim() === "AD");

    if (window.currentAuthenticatedUser && window.currentAuthenticatedUser.uid) {
      return {
        uid: String(window.currentAuthenticatedUser.uid),
        role: window.currentAuthenticatedUser.role || (isDoc ? "doctor" : "patient"),
        name: window.currentAuthenticatedUser.name || (isDoc ? "Admin Doctor" : "Patient User"),
        email: window.currentAuthenticatedUser.email || (isDoc ? "admin@gmail.com" : "patient@gmail.com")
      };
    }

    try {
      const storedDoc = sessionStorage.getItem("authenticated_doctor") || localStorage.getItem("authenticated_doctor");
      const storedPat = sessionStorage.getItem("authenticated_patient") || localStorage.getItem("authenticated_patient");
      if (isDoc && storedDoc) {
        const d = JSON.parse(storedDoc);
        return { uid: String(d.uid || "3001"), role: "doctor", name: d.name || "Admin Doctor", email: d.email || "admin@gmail.com" };
      }
      if (!isDoc && storedPat) {
        const p = JSON.parse(storedPat);
        return { uid: String(p.uid || "4001"), role: "patient", name: p.name || "Patient User", email: p.email || "patient@gmail.com" };
      }
    } catch (_) { }

    return isDoc
      ? { uid: "3001", role: "doctor", name: "Admin Doctor", email: "admin@gmail.com" }
      : { uid: "4001", role: "patient", name: "Patient User", email: "patient@gmail.com" };
  }

  // Format relative timestamp
  function formatTimeAgo(dateString) {
    if (!dateString) return "Just now";
    try {
      const past = new Date(dateString.replace(" ", "T") + (dateString.includes("Z") ? "" : "Z")).getTime();
      const diffSec = Math.floor((Date.now() - past) / 1000);
      if (isNaN(diffSec) || diffSec < 45) return "Just now";
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      return `${Math.floor(diffSec / 86400)}d ago`;
    } catch (_) {
      return "Recently";
    }
  }

  // HTML escaping helper
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Normalize backend notification data into a clean, compact, healthcare-grade format
  function normalizeNotification(notif) {
    const rawType = (notif.type || "system").toLowerCase();
    let rawTitle = (notif.title || "Notification").trim();
    let rawMsg = (notif.message || "").trim();
    const isDemo = Boolean((notif.event_key && notif.event_key.startsWith("demo_")) || rawTitle.includes("[DEMO]") || rawMsg.includes("[DEMO]"));

    // 1. Identify primary entity identifiers
    let reportId = "";
    let patientId = "";
    let patientName = "";
    let attenderName = "";
    let appointmentId = "";

    // Extract Report ID (RPT-...)
    if (notif.reference_type === "report" && notif.reference_id && notif.reference_id.toUpperCase().startsWith("RPT-")) {
      reportId = notif.reference_id.trim();
    } else if (notif.related_report_id) {
      reportId = notif.related_report_id.trim();
    }
    if (!reportId) {
      const rptMatch = (rawTitle + " " + rawMsg + " " + (notif.action_url || "")).match(/(RPT-[A-Za-z0-9_-]+)/i);
      if (rptMatch) reportId = rptMatch[1].trim();
    }

    // Extract Appointment ID (APT-...)
    if (notif.reference_type === "appointment" && notif.reference_id) {
      appointmentId = notif.reference_id.trim();
    } else if (notif.related_appointment_id) {
      appointmentId = notif.related_appointment_id.startsWith("APT-") ? notif.related_appointment_id.trim() : `APT-${notif.related_appointment_id}`.trim();
    }
    if (!appointmentId) {
      const aptMatch = (rawTitle + " " + rawMsg + " " + (notif.action_url || "")).match(/(APT-[A-Za-z0-9_-]+)/i);
      if (aptMatch) appointmentId = aptMatch[1].trim();
    }

    // Extract Patient ID from action_url, e.g. patient_id=4001, or conversation ID, or message
    if (notif.action_url) {
      const patUrlMatch = notif.action_url.match(/patient_id=([A-Za-z0-9_-]+)/i);
      if (patUrlMatch) patientId = patUrlMatch[1].trim();
    }
    if (!patientId && notif.related_patient_id) {
      patientId = String(notif.related_patient_id).trim();
    }
    if (!patientId && notif.reference_id && notif.reference_id.startsWith("conv_")) {
      const convPatMatch = notif.reference_id.match(/conv_\d+_(\d+)/);
      if (convPatMatch) patientId = convPatMatch[1].trim();
    }
    if (!patientId) {
      const patParenMatch = (rawTitle + " " + rawMsg).match(/\b(?:patient|for)\s+[^()]+?\s*\(([P\d]{3,8}|[A-Za-z0-9_-]{4,10})\)/i);
      if (patParenMatch && !patParenMatch[1].toUpperCase().startsWith("RPT-") && !patParenMatch[1].toUpperCase().startsWith("APT-")) {
        patientId = patParenMatch[1].trim();
      }
    }

    // Extract Patient Name from message/title
    const patUserMatch = rawMsg.match(/(?:to\s+patient|for\s+patient|for)\s+([A-Z][a-zA-Z0-9\s.]+?)(?:\s*\((?:[^)]+)\)|\s*failed:|\s*has\s+been|\s+is\s+scheduled)/i);
    if (patUserMatch) {
      patientName = patUserMatch[1].trim();
    } else {
      const patStartMatch = rawMsg.match(/^Patient\s+([A-Z][a-zA-Z0-9\s.]+?)(?:\s*\((?:[^)]+)\)|\s+is\s+scheduled)/i);
      if (patStartMatch) {
        patientName = patStartMatch[1].trim();
      }
    }

    // Detect Attender in Chat or Title
    const isAttender = rawTitle.toLowerCase().includes("attender") || rawMsg.toLowerCase().includes("attender") || notif.sender_role === "attender";
    if (isAttender) {
      const attMatch = rawTitle.match(/from\s+([^(]+?)(?:\s*\((?:attender\s*(?:for)?\s*([^)]*))\)|\s*$)/i);
      if (attMatch) {
        attenderName = attMatch[1].replace(/attender/i, "").trim();
        if (attMatch[2] && attMatch[2].trim()) {
          patientName = attMatch[2].trim();
        }
      }
    } else if (rawType === "chat" || rawType === "chat_message") {
      const chatFromMatch = rawTitle.match(/New message from\s+(.+)$/i);
      if (chatFromMatch && !patientName) {
        patientName = chatFromMatch[1].trim();
      }
    }

    // Default patient fallback if still empty
    if (!patientName && patientId === "4001") {
      patientName = "Patient User";
    }

    // 2. Classify event, semantic styling, title, issue, and actions
    let sourceLabel = "System Notice";
    let semanticClass = "type-system";
    let iconSvg = "";
    let title = "Notification";
    let issueText = "";
    let recommendedAction = "";
    let messageQuote = "";
    let generalDesc = "";
    let actionLabel = "";
    let deliveryStatus = "";

    const isDeliveryFailure = rawType === "email_failure" || rawType === "email_failed" || rawTitle.toLowerCase().includes("delivery failed");
    const isDelivered = rawType === "report_delivered" || rawTitle.toLowerCase().includes("report delivered");
    const isGenerated = rawType === "report_generated" || rawTitle.toLowerCase().includes("report generated");
    const isChat = rawType === "chat" || rawType === "chat_message" || rawTitle.toLowerCase().includes("message from");
    const isAppointment = rawType === "appointment" || rawTitle.toLowerCase().includes("appointment");

    if (isDeliveryFailure) {
      sourceLabel = "Report Delivery Issue";
      semanticClass = "type-danger";
      title = "Patient Report Delivery Failed";
      actionLabel = "View Report";
      deliveryStatus = notif.resolved_at ? "Resolved" : "Delivery Failed";

      // Alert icon
      iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;

      // Extract actual failure reason returned by backend
      let rawReason = "";
      if (rawMsg.includes("failed:")) {
        rawReason = rawMsg.split("failed:")[1].trim();
      } else if (rawMsg.includes("Error:") || rawMsg.includes("error:")) {
        rawReason = rawMsg.split(/error:/i)[1].trim();
      } else {
        rawReason = rawMsg;
      }

      if (rawReason.toLowerCase().includes("inbox is full") || rawReason.toLowerCase().includes("mailbox quota")) {
        issueText = "The report email could not be delivered because the patient's inbox is full.";
        recommendedAction = "Contact the patient or update their email address, then retry delivery.";
      } else if (rawReason.toLowerCase().includes("no registered email")) {
        issueText = "The report email could not be delivered because the patient has no registered email address.";
        recommendedAction = "Update the patient's email address in their record, then retry delivery.";
      } else if (rawReason.toLowerCase().includes("invalid") || rawReason.toLowerCase().includes("recipient")) {
        issueText = "The report email could not be delivered due to an invalid recipient address.";
        recommendedAction = "Verify and correct the patient's email address, then retry delivery.";
      } else if (rawReason.toLowerCase().includes("connection") || rawReason.toLowerCase().includes("smtp") || rawReason.toLowerCase().includes("timeout")) {
        issueText = `Delivery service temporarily unavailable (${rawReason.replace(/^Email delivery failed:?\s*/i, "").trim()}).`;
        recommendedAction = "Verify hospital SMTP service connection, then retry delivery.";
      } else {
        // Use actual backend failure reason accurately (Requirement 1)
        let cleanedReason = rawReason.replace(/^Email delivery failed:?\s*/i, "").trim();
        const pleaseSplit = cleanedReason.split(/Please\s+/i);
        issueText = pleaseSplit[0].trim();
        if (!issueText.endsWith(".")) issueText += ".";
        if (pleaseSplit[1]) {
          recommendedAction = "Please " + pleaseSplit[1].trim();
        } else {
          recommendedAction = "Review patient contact details and retry delivery from the report viewer.";
        }
      }

    } else if (isDelivered) {
      sourceLabel = "Report Delivered";
      semanticClass = "type-success";
      title = "Patient Report Delivered";
      actionLabel = "View Report";
      deliveryStatus = "Delivered";

      // Success check icon
      iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;

      // Clean preview without exposing raw email address unnecessarily (Requirement 5)
      generalDesc = "Ultrasound diagnostic report was delivered successfully to the patient's verified email.";

    } else if (isGenerated) {
      sourceLabel = "Report Generated";
      semanticClass = "type-success";
      title = "Diagnostic Report Generated";
      actionLabel = "View Report";

      // File text icon
      iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>`;

      generalDesc = "Ultrasound diagnostic report generated and ready for clinical sign-off and distribution.";

    } else if (isChat) {
      if (isAttender) {
        sourceLabel = "Attender Message";
        title = "New Message from Attender";
      } else {
        sourceLabel = "Patient Message";
        title = "New Message from Patient";
      }
      semanticClass = "type-chat";
      actionLabel = "Open Chat";

      // Chat bubble icon
      iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;

      messageQuote = rawMsg;

    } else if (isAppointment) {
      sourceLabel = "Appointment Notice";
      semanticClass = "type-appointment";
      title = "Appointment Scheduled";
      actionLabel = "View Appointment";

      // Calendar icon
      iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;

      generalDesc = rawMsg.replace(/\[DEMO\]\s*/i, "");

    } else {
      sourceLabel = "System Notice";
      semanticClass = "type-system";
      title = rawTitle.replace(/\[DEMO\]\s*/i, "") || "System Notice";
      actionLabel = notif.action_url ? "View Details" : "";

      // Info circle icon
      iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;

      generalDesc = rawMsg.replace(/\[DEMO\]\s*/i, "");
    }

    const hasTags = Boolean(patientName || patientId || attenderName || reportId || appointmentId || deliveryStatus || isDemo);

    return {
      sourceLabel,
      semanticClass,
      iconSvg,
      title,
      patientName,
      patientId,
      attenderName,
      reportId,
      appointmentId,
      deliveryStatus,
      isDemo,
      hasTags,
      issueText,
      recommendedAction,
      messageQuote,
      generalDesc,
      actionLabel,
      timeAgo: formatTimeAgo(notif.created_at)
    };
  }

  // Filter and deduplicate notifications to prevent duplicate failure events (Requirement 5)
  function filterAndDeduplicateNotifications(rawList) {
    if (!rawList || !rawList.length) return [];

    // Identify reports that have confirmed delivery
    const deliveredReports = new Set();
    rawList.forEach(n => {
      const type = (n.type || "").toLowerCase();
      const rId = n.reference_id || "";
      if ((type === "report_delivered" || (n.title && n.title.toLowerCase().includes("report delivered"))) && rId) {
        deliveredReports.add(rId);
      }
    });

    const seenEventKeys = new Set();
    const seenFailureReports = new Set();
    const deduplicated = [];

    for (const notif of rawList) {
      const type = (notif.type || "").toLowerCase();
      const rId = notif.reference_id || "";
      const eventKey = notif.event_key || "";

      // 1. Deduplicate by explicit event_key
      if (eventKey) {
        if (seenEventKeys.has(eventKey)) continue;
        seenEventKeys.add(eventKey);
      }

      // 2. Prevent duplicate notifications for the same underlying failure event
      if (type === "email_failure" || type === "email_failed" || (notif.title && notif.title.toLowerCase().includes("delivery failed"))) {
        // If delivery was confirmed successful for this report, suppress obsolete failure card
        if (rId && deliveredReports.has(rId)) {
          continue;
        }
        // If multiple failure records exist for the same report ID, keep only the latest
        if (rId) {
          if (seenFailureReports.has(rId)) continue;
          seenFailureReports.add(rId);
        }
      }

      deduplicated.push(notif);
    }

    return deduplicated;
  }

  // =========================================================================
  // 1. NOTIFICATION SYSTEM
  // =========================================================================

  function initTorusNotificationSystem() {
    const bellBtn = document.getElementById("docDashNotifBtn");
    const popoverEl = document.getElementById("docDashNotifPopover");
    const markAllBtn = document.getElementById("docDashMarkAllReadBtn");

    if (!bellBtn || !popoverEl) return;

    // Toggle popover on bell click
    bellBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      const isVisible = popoverEl.style.display === "block";
      if (isVisible) {
        closeNotificationPopover();
      } else {
        openNotificationPopover();
      }
    });

    // Close on click outside
    document.addEventListener("click", function (e) {
      const wrap = document.getElementById("docDashNotifWrap");
      if (wrap && !wrap.contains(e.target)) {
        closeNotificationPopover();
      }
    });

    // Close on Escape
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeNotificationPopover();
      }
    });

    // Mark all as read
    if (markAllBtn) {
      markAllBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        markAllNotificationsAsRead();
      });
    }

    // Initial fetch and start periodic polling
    fetchNotifications();
    if (notifPollTimer) clearInterval(notifPollTimer);
    notifPollTimer = setInterval(fetchNotifications, 8000);
  }

  function openNotificationPopover() {
    const popoverEl = document.getElementById("docDashNotifPopover");
    const profilePopover = document.getElementById("docDashProfilePopover");
    if (profilePopover) profilePopover.style.display = "none";
    if (popoverEl) {
      popoverEl.style.display = "block";
      renderNotificationsList();
    }
  }

  function closeNotificationPopover() {
    const popoverEl = document.getElementById("docDashNotifPopover");
    if (popoverEl) popoverEl.style.display = "none";
  }

  function fetchNotifications() {
    const user = getTorusUser();
    fetch(`/api/notifications?user_id=${encodeURIComponent(user.uid)}&role=${encodeURIComponent(user.role)}`)
      .then(res => res.json())
      .then(data => {
        if (data && data.success) {
          const raw = data.notifications || [];
          activeNotifications = filterAndDeduplicateNotifications(raw);
          unreadNotifCount = activeNotifications.filter(n => !n.is_read).length;
          updateNotificationBadges();
          if (document.getElementById("docDashNotifPopover")?.style.display === "block") {
            renderNotificationsList();
          }
        }
      })
      .catch(err => {
        console.warn("[Notifications] Fetch error:", err);
      });
  }

  function updateNotificationBadges() {
    const badgeEl = document.getElementById("docDashNotifBadge");
    const countPill = document.getElementById("docDashNotifCountPill");

    if (badgeEl) {
      if (unreadNotifCount > 0) {
        badgeEl.textContent = unreadNotifCount > 99 ? "99+" : unreadNotifCount;
        badgeEl.style.display = "inline-flex";
      } else {
        badgeEl.style.display = "none";
      }
    }

    if (countPill) {
      if (unreadNotifCount > 0) {
        countPill.textContent = `${unreadNotifCount} new`;
        countPill.style.display = "inline-flex";
      } else {
        countPill.style.display = "none";
      }
    }
  }

  function renderNotificationsList() {
    const listEl = document.getElementById("docDashNotifList");
    if (!listEl) return;

    if (!activeNotifications || activeNotifications.length === 0) {
      listEl.innerHTML = `
        <div class="ddash-notif-empty" id="docDashNotifEmpty">
          <div class="ddash-notif-empty-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
              <line x1="2" y1="2" x2="22" y2="22"></line>
            </svg>
          </div>
          <div class="ddash-notif-empty-text">No notifications</div>
          <div class="ddash-notif-empty-subtext">You're all caught up with clinic updates</div>
        </div>
      `;
      return;
    }

    let html = "";
    activeNotifications.forEach(notif => {
      const isUnread = !notif.is_read;
      const n = normalizeNotification(notif);

      html += `
        <div class="ddash-notif-item ${isUnread ? "unread" : ""}" data-notif-id="${notif.id}" role="button" tabindex="0">
          <div class="ddash-notif-item-left">
            <div class="ddash-notif-item-icon ${n.semanticClass}">
              ${n.iconSvg}
            </div>
          </div>
          <div class="ddash-notif-item-content">
            <div class="ddash-notif-top-meta">
              <span class="ddash-notif-source-badge ${n.semanticClass}">${escapeHtml(n.sourceLabel)}</span>
              <span class="ddash-notif-item-time">${escapeHtml(n.timeAgo)}</span>
            </div>

            <div class="ddash-notif-item-title">${escapeHtml(n.title)}</div>

            ${n.hasTags ? `
              <div class="ddash-notif-entity-tags">
                ${n.patientName ? `<span class="ddash-tag patient-tag">Patient: <strong>${escapeHtml(n.patientName)}</strong></span>` : ""}
                ${n.patientId ? `<span class="ddash-tag">Patient ID: <strong>${escapeHtml(n.patientId)}</strong></span>` : ""}
                ${n.attenderName ? `<span class="ddash-tag attender-tag">Attender: <strong>${escapeHtml(n.attenderName)}</strong></span>` : ""}
                ${n.reportId ? `<span class="ddash-tag report-tag">${escapeHtml(n.reportId)}</span>` : ""}
                ${n.deliveryStatus ? `<span class="ddash-tag status-${n.deliveryStatus === "Delivered" ? "delivered" : "failed"}">Status: <strong>${escapeHtml(n.deliveryStatus)}</strong></span>` : ""}
                ${n.appointmentId ? `<span class="ddash-tag">${escapeHtml(n.appointmentId)}</span>` : ""}
                ${n.isDemo ? `<span class="ddash-tag demo-tag">Demo</span>` : ""}
              </div>
            ` : ""}

            ${n.issueText ? `
              <div class="ddash-notif-issue-box">
                <span class="ddash-issue-label">Issue:</span> ${escapeHtml(n.issueText)}
              </div>
            ` : ""}

            ${n.recommendedAction ? `
              <div class="ddash-notif-rec-action">
                <span class="ddash-rec-label">Recommended action:</span> ${escapeHtml(n.recommendedAction)}
              </div>
            ` : ""}

            ${n.messageQuote ? `
              <div class="ddash-notif-message-quote" title="${escapeHtml(notif.message || "")}">
                &ldquo;${escapeHtml(n.messageQuote)}&rdquo;
              </div>
            ` : ""}

            ${n.generalDesc ? `
              <div class="ddash-notif-item-desc" title="${escapeHtml(notif.message || "")}">
                ${escapeHtml(n.generalDesc)}
              </div>
            ` : ""}

            <div class="ddash-notif-item-footer">
              <div class="ddash-notif-footer-left">
                ${n.actionLabel ? `
                  <button type="button" class="ddash-notif-action-btn" data-action="navigate" title="${escapeHtml(n.actionLabel)}">
                    ${escapeHtml(n.actionLabel)} &rarr;
                  </button>
                ` : ""}
              </div>
              <div class="ddash-notif-footer-right">
                ${isUnread ? `
                  <button type="button" class="ddash-notif-mark-item-btn" data-action="mark-read" title="Mark as read">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    <span>Mark read</span>
                  </button>
                ` : ""}
              </div>
            </div>
          </div>
          ${isUnread ? `<span class="ddash-notif-unread-dot" title="Unread notification"></span>` : ""}
        </div>
      `;
    });

    listEl.innerHTML = html;

    // Item click handling
    listEl.querySelectorAll(".ddash-notif-item").forEach(card => {
      const notifId = card.getAttribute("data-notif-id");
      const notif = activeNotifications.find(item => String(item.id) === String(notifId));
      if (!notif) return;

      const readBtn = card.querySelector('[data-action="mark-read"]');
      if (readBtn) {
        readBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          markNotificationAsRead(notif.id);
        });
      }

      card.addEventListener("click", function (e) {
        if (e.target.closest('[data-action="mark-read"]')) return;

        if (!notif.is_read) {
          markNotificationAsRead(notif.id);
        }

        closeNotificationPopover();

        const n = normalizeNotification(notif);
        if (n.reportId || notif.reference_type === "report" || notif.related_report_id) {
          const repId = n.reportId || notif.reference_id || notif.related_report_id;
          const patId = n.patientId || notif.related_patient_id || "4001";
          window.location.href = `/report-generation.html?report_id=${encodeURIComponent(repId)}&patient_id=${encodeURIComponent(patId)}`;
        } else if (notif.reference_type === "conversation" || notif.related_conversation_id || (notif.action_url && notif.action_url.includes("conv="))) {
          const convMatch = notif.action_url ? notif.action_url.match(/conv=([^&]+)/) : null;
          const convId = notif.related_conversation_id || notif.reference_id || (convMatch ? convMatch[1] : "conv_3001_4001");
          if (typeof window.toggleTorusChatDrawer === "function") {
            window.toggleTorusChatDrawer(true, convId);
          }
        } else if (notif.action_url) {
          if (notif.action_url.startsWith("#")) {
            const navLink = document.querySelector(`.ddash-nav-item[href="${notif.action_url}"]`);
            if (navLink) navLink.click();
          } else {
            window.location.href = notif.action_url;
          }
        }
      });
    });
  }

  function markNotificationAsRead(notifId) {
    fetch(`/api/notifications/${encodeURIComponent(notifId)}/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    })
      .then(res => res.json())
      .then(data => {
        if (data && data.success) {
          const item = activeNotifications.find(n => String(n.id) === String(notifId));
          if (item && !item.is_read) {
            item.is_read = 1;
            unreadNotifCount = Math.max(0, unreadNotifCount - 1);
            updateNotificationBadges();

            // Smooth inline DOM update
            const cardEl = document.querySelector(`.ddash-notif-item[data-notif-id="${notifId}"]`);
            if (cardEl) {
              cardEl.classList.remove("unread");
              const dot = cardEl.querySelector(".ddash-notif-unread-dot");
              if (dot) dot.remove();
              const readBtn = cardEl.querySelector('[data-action="mark-read"]');
              if (readBtn) readBtn.remove();
            }
          }
        }
      })
      .catch(err => console.warn("[Notifications] Mark read error:", err));
  }

  function markAllNotificationsAsRead() {
    const user = getTorusUser();
    fetch("/api/notifications/read-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.uid, role: user.role })
    })
      .then(res => res.json())
      .then(data => {
        if (data && data.success) {
          activeNotifications.forEach(n => { n.is_read = 1; });
          unreadNotifCount = 0;
          updateNotificationBadges();
          renderNotificationsList();
          if (typeof showToastAlert === "function") {
            showToastAlert("All notifications marked as read.", "success");
          }
        }
      })
      .catch(err => console.warn("[Notifications] Mark all read error:", err));
  }

  // =========================================================================
  // 2. TWO-WAY CHAT SYSTEM
  // =========================================================================

  function initTorusChatSystem() {
    const floatingBtn = document.getElementById("torusFloatingChatBtn");
    const drawerEl = document.getElementById("torusChatDrawer");
    const backdropEl = document.getElementById("torusChatBackdrop");
    const closeBtn = document.getElementById("torusChatCloseBtn");
    const tabChatBtn = document.getElementById("torusTabClinicalChat");
    const tabAiBtn = document.getElementById("torusTabAiSupport");
    const convSelect = document.getElementById("torusChatConvSelect");
    const chatForm = document.getElementById("torusChatForm");

    if (!floatingBtn || !drawerEl) return;

    // Toggle drawer from floating launcher
    floatingBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      window.toggleTorusChatDrawer();
    });

    // Also bind sidebar chat links if present on the screen
    const sidebarDocChat = document.getElementById("docDashSidebarChatBtn");
    const sidebarPatChat = document.getElementById("patDashSidebarChatBtn");
    [sidebarDocChat, sidebarPatChat].forEach(btn => {
      if (btn) {
        btn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          window.toggleTorusChatDrawer(true);
        });
      }
    });

    // Close on backdrop or close button
    if (backdropEl) backdropEl.addEventListener("click", () => window.toggleTorusChatDrawer(false));
    if (closeBtn) closeBtn.addEventListener("click", () => window.toggleTorusChatDrawer(false));

    // Close on Escape key
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isChatDrawerOpen) {
        window.toggleTorusChatDrawer(false);
      }
    });

    // Switch between Clinical Chat and AI Support tabs
    if (tabChatBtn && tabAiBtn) {
      tabChatBtn.addEventListener("click", function () {
        tabChatBtn.classList.add("active");
        tabAiBtn.classList.remove("active");
        document.getElementById("torusViewClinicalChat").style.display = "flex";
        document.getElementById("torusViewAiSupport").style.display = "none";
      });

      tabAiBtn.addEventListener("click", function () {
        tabAiBtn.classList.add("active");
        tabChatBtn.classList.remove("active");
        document.getElementById("torusViewClinicalChat").style.display = "none";
        document.getElementById("torusViewAiSupport").style.display = "flex";
        initAiAssistantWelcome();
      });
    }

    // Conversation dropdown change
    if (convSelect) {
      convSelect.addEventListener("change", function () {
        currentActiveConvId = this.value;
        loadConversationMessages(currentActiveConvId);
      });
    }

    // Form submission (Send message)
    if (chatForm) {
      chatForm.addEventListener("submit", function (e) {
        e.preventDefault();
        sendChatMessage();
      });
    }

    const chatInput = document.getElementById("torusChatMessageInput");
    if (chatInput) {
      chatInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendChatMessage();
        }
      });
    }

    // Initial check for unread chat messages
    fetchConversations(false);
  }

  // Global toggle function
  window.toggleTorusChatDrawer = function (open, targetConvId) {
    const drawerEl = document.getElementById("torusChatDrawer");
    if (!drawerEl) return;

    // Detect actual visible state from inline style or computed display
    const isCurrentlyVisible = drawerEl.style.display === "flex" ||
                               drawerEl.style.display === "block" ||
                               drawerEl.classList.contains("active");

    const shouldOpen = open !== undefined ? Boolean(open) : !isCurrentlyVisible;
    isChatDrawerOpen = shouldOpen;

    if (shouldOpen) {
      drawerEl.style.display = "flex";
      drawerEl.classList.add("active");
      drawerEl.setAttribute("aria-hidden", "false");
      fetchConversations(true, targetConvId);
      if (chatPollTimer) clearInterval(chatPollTimer);
      chatPollTimer = setInterval(() => {
        if (isChatDrawerOpen && currentActiveConvId) {
          loadConversationMessages(currentActiveConvId, false);
        }
      }, 3500);
    } else {
      drawerEl.style.display = "none";
      drawerEl.classList.remove("active");
      drawerEl.setAttribute("aria-hidden", "true");
      if (chatPollTimer) {
        clearInterval(chatPollTimer);
        chatPollTimer = null;
      }
    }
  };

  function fetchConversations(shouldLoadMessages = true, targetConvId = null) {
    const user = getTorusUser();
    fetch(`/api/conversations?user_id=${encodeURIComponent(user.uid)}&role=${encodeURIComponent(user.role)}`)
      .then(res => res.json())
      .then(data => {
        if (data && data.success) {
          activeConversations = data.conversations || [];
          updateChatBadges();
          populateConversationSelect(targetConvId);

          if (shouldLoadMessages && currentActiveConvId) {
            loadConversationMessages(currentActiveConvId, true);
          }
        }
      })
      .catch(err => console.warn("[Chat] Fetch conversations error:", err));
  }

  function updateChatBadges() {
    let totalUnread = 0;
    activeConversations.forEach(c => {
      totalUnread += (c.unread_count || 0);
    });

    const floatingBadge = document.getElementById("torusFloatingChatBadge");
    const sidebarDocBadge = document.getElementById("docDashSidebarChatBadge");
    const sidebarPatBadge = document.getElementById("patDashSidebarChatBadge");

    if (floatingBadge) {
      if (totalUnread > 0) {
        floatingBadge.textContent = totalUnread > 99 ? "99+" : totalUnread;
        floatingBadge.style.display = "inline-flex";
      } else {
        floatingBadge.style.display = "none";
      }
    }

    [sidebarDocBadge, sidebarPatBadge].forEach(badge => {
      if (badge) {
        if (totalUnread > 0) {
          badge.textContent = totalUnread > 99 ? "99+" : totalUnread;
          badge.style.display = "inline-flex";
        } else {
          badge.style.display = "none";
        }
      }
    });
  }

  function populateConversationSelect(targetConvId) {
    const select = document.getElementById("torusChatConvSelect");
    const recipientLabel = document.getElementById("torusChatRecipientName");
    const user = getTorusUser();
    if (!select) return;

    if (activeConversations.length === 0) {
      select.innerHTML = `<option value="">No Active Conversations</option>`;
      if (recipientLabel) recipientLabel.textContent = "Clinical Support";
      return;
    }

    let optionsHtml = "";
    activeConversations.forEach(c => {
      const otherName = user.role === "doctor"
        ? (c.patient_name || `Patient ${c.patient_id}`)
        : (c.doctor_name || `Dr. ${c.doctor_id}`);
      optionsHtml += `<option value="${c.id}">${escapeHtml(otherName)}</option>`;
    });

    select.innerHTML = optionsHtml;

    if (targetConvId && activeConversations.some(c => c.id === targetConvId)) {
      select.value = targetConvId;
      currentActiveConvId = targetConvId;
    } else if (!currentActiveConvId || !activeConversations.some(c => c.id === currentActiveConvId)) {
      currentActiveConvId = activeConversations[0].id;
      select.value = currentActiveConvId;
    }

    const currentConv = activeConversations.find(c => c.id === currentActiveConvId);
    if (currentConv && recipientLabel) {
      recipientLabel.textContent = user.role === "doctor"
        ? `${currentConv.patient_name || "Patient"} (${currentConv.patient_id})`
        : (currentConv.doctor_name || "Dr. Admin Doctor");
    }
  }

  function loadConversationMessages(convId, autoScroll = true) {
    if (!convId) return;
    const user = getTorusUser();
    fetch(`/api/conversations/${encodeURIComponent(convId)}/messages`)
      .then(res => res.json())
      .then(data => {
        if (data && data.success) {
          renderMessagesList(data.messages || [], autoScroll);
          if (autoScroll) {
            // Mark conversation as read on initial open
            fetch(`/api/conversations/${encodeURIComponent(convId)}/read`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ user_id: user.uid })
            }).then(() => {
              const conv = activeConversations.find(c => c.id === convId);
              if (conv) conv.unread_count = 0;
              updateChatBadges();
            }).catch(() => { });
          }
        }
      })
      .catch(err => console.warn("[Chat] Load messages error:", err));
  }

  function renderMessagesList(messages, autoScroll) {
    const listEl = document.getElementById("torusChatMessagesList");
    if (!listEl) return;

    const user = getTorusUser();

    if (messages.length === 0) {
      listEl.innerHTML = `
        <div class="torus-chat-feed-empty">
          <div class="torus-chat-feed-empty-icon">💬</div>
          <div>No messages yet. Send a message to start conversation.</div>
        </div>
      `;
      return;
    }

    let html = "";
    messages.forEach(msg => {
      const isMine = String(msg.sender_id) === String(user.uid) || msg.sender_role === user.role;
      const timeStr = formatMessageTime(msg.created_at);

      html += `
        <div class="torus-message-row ${isMine ? "outgoing" : "incoming"}">
          <div class="torus-message-bubble ${isMine ? "bubble-mine" : "bubble-theirs"}">
            ${!isMine ? `<div class="torus-message-sender-name">${escapeHtml(msg.sender_name || "Care Team")}</div>` : ""}
            <div class="torus-message-text">${escapeHtml(msg.content)}</div>
            <div class="torus-message-meta">
              <span class="torus-message-time">${timeStr}</span>
              ${isMine ? `<span class="torus-message-status" title="Sent">✓✓</span>` : ""}
            </div>
          </div>
        </div>
      `;
    });

    listEl.innerHTML = html;

    if (autoScroll) {
      listEl.scrollTop = listEl.scrollHeight;
    }
  }

  function formatMessageTime(isoString) {
    if (!isoString) return "";
    try {
      const d = new Date(isoString.replace(" ", "T") + (isoString.includes("Z") ? "" : "Z"));
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
      return "";
    }
  }

  function sendChatMessage() {
    if (isSendingMessage) return;
    const input = document.getElementById("torusChatMessageInput");
    const sendBtn = document.getElementById("torusChatSendBtn");
    if (!input || !currentActiveConvId) return;

    const text = input.value.trim();
    if (!text) return;

    const user = getTorusUser();
    isSendingMessage = true;
    if (sendBtn) sendBtn.disabled = true;

    fetch(`/api/conversations/${encodeURIComponent(currentActiveConvId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sender_id: user.uid,
        sender_role: user.role,
        sender_name: user.name,
        content: text
      })
    })
      .then(res => res.json())
      .then(data => {
        isSendingMessage = false;
        if (sendBtn) sendBtn.disabled = false;
        if (data && data.success) {
          input.value = "";
          loadConversationMessages(currentActiveConvId, true);
        } else {
          alert("Failed to send message: " + (data?.error || "Unknown error"));
        }
      })
      .catch(err => {
        isSendingMessage = false;
        if (sendBtn) sendBtn.disabled = false;
        console.error("[Chat] Send error:", err);
      });
  }

  // =========================================================================
  // 3. AI SUPPORT ASSISTANT
  // =========================================================================

  function initTorusAiAssistant() {
    const aiForm = document.getElementById("torusAiForm");
    if (aiForm) {
      aiForm.addEventListener("submit", function (e) {
        e.preventDefault();
        sendAiQuery();
      });
    }
  }

  function initAiAssistantWelcome() {
    const user = getTorusUser();
    const chipsContainer = document.getElementById("torusAiQuickChips");
    const feed = document.getElementById("torusAiMessagesList");

    if (chipsContainer) {
      const doctorChips = [
        "Which patients have pending reports?",
        "Which report emails failed today?",
        "Show my upcoming appointments.",
        "Why did this report delivery fail?"
      ];

      const patientChips = [
        "Is my report available?",
        "How can I download my report?",
        "When is my next appointment?",
        "Why did my report email fail?"
      ];

      const chips = user.role === "doctor" ? doctorChips : patientChips;
      chipsContainer.innerHTML = chips.map(q => `
        <button type="button" class="torus-ai-chip" data-query="${escapeHtml(q)}">${escapeHtml(q)}</button>
      `).join("");

      chipsContainer.querySelectorAll(".torus-ai-chip").forEach(btn => {
        btn.addEventListener("click", function () {
          const q = this.getAttribute("data-query");
          const input = document.getElementById("torusAiMessageInput");
          if (input) input.value = q;
          sendAiQuery();
        });
      });
    }

    if (feed && feed.children.length === 0) {
      feed.innerHTML = `
        <div class="torus-message-row incoming">
          <div class="torus-message-bubble bubble-ai">
            <div class="torus-ai-badge">🤖 TORUS AI Support • Operational Assistant</div>
            <div class="torus-message-text">
              Hello ${escapeHtml(user.name)}! I can provide real-time status updates on diagnostic reports, email delivery, and tele-ultrasound appointments from verified clinic records.
              <br/><br/>
              How can I assist you today?
            </div>
            <div class="torus-ai-disclaimer">Non-clinical guidance. For medical questions, consult your attending doctor.</div>
          </div>
        </div>
      `;
    }
  }

  function sendAiQuery() {
    if (isAiQuerying) return;
    const input = document.getElementById("torusAiMessageInput");
    const sendBtn = document.getElementById("torusAiSendBtn");
    const feed = document.getElementById("torusAiMessagesList");
    if (!input || !feed) return;

    const query = input.value.trim();
    if (!query) return;

    const user = getTorusUser();
    isAiQuerying = true;
    if (sendBtn) sendBtn.disabled = true;

    // Append user query bubble
    feed.innerHTML += `
      <div class="torus-message-row outgoing">
        <div class="torus-message-bubble bubble-mine">
          <div class="torus-message-text">${escapeHtml(query)}</div>
          <div class="torus-message-meta"><span class="torus-message-time">Just now</span></div>
        </div>
      </div>
    `;

    // Append thinking bubble
    const thinkingId = "aiThinking_" + Date.now();
    feed.innerHTML += `
      <div class="torus-message-row incoming" id="${thinkingId}">
        <div class="torus-message-bubble bubble-ai">
          <div class="torus-ai-thinking">
            <span></span><span></span><span></span> Checking verified records...
          </div>
        </div>
      </div>
    `;

    feed.scrollTop = feed.scrollHeight;
    input.value = "";

    fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        user_id: user.uid,
        role: user.role
      })
    })
      .then(res => res.json())
      .then(data => {
        isAiQuerying = false;
        if (sendBtn) sendBtn.disabled = false;
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();

        if (data && data.success) {
          const actionsHtml = (data.suggested_actions || []).map(act => `
            <button type="button" class="torus-ai-action-btn" data-action="${act.action}" data-target="${act.target}">
              ${escapeHtml(act.label)} &rarr;
            </button>
          `).join("");

          feed.innerHTML += `
            <div class="torus-message-row incoming">
              <div class="torus-message-bubble bubble-ai">
                <div class="torus-ai-badge">🤖 TORUS AI Support • Verified Record Query</div>
                <div class="torus-message-text">${escapeHtml(data.answer).replace(/\n/g, "<br/>")}</div>
                ${actionsHtml ? `<div class="torus-ai-actions-wrap">${actionsHtml}</div>` : ""}
                <div class="torus-ai-disclaimer">TORUS Clinical Telemetry • Non-clinical guidance</div>
              </div>
            </div>
          `;

          // Bind suggested actions
          feed.querySelectorAll(".torus-ai-action-btn").forEach(actBtn => {
            actBtn.addEventListener("click", function () {
              const act = this.getAttribute("data-action");
              const target = this.getAttribute("data-target");
              executeAiAction(act, target);
            });
          });

          feed.scrollTop = feed.scrollHeight;
        } else {
          feed.innerHTML += `
            <div class="torus-message-row incoming">
              <div class="torus-message-bubble bubble-ai">
                <div class="torus-message-text" style="color: #f87171;">
                  Unable to retrieve records: ${escapeHtml(data?.error || "Connection error")}
                </div>
              </div>
            </div>
          `;
          feed.scrollTop = feed.scrollHeight;
        }
      })
      .catch(err => {
        isAiQuerying = false;
        if (sendBtn) sendBtn.disabled = false;
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();
        console.error("[AI] Chat error:", err);
      });
  }

  function executeAiAction(action, target) {
    if (action === "view_report") {
      window.location.href = `/report-generation.html?report_id=${encodeURIComponent(target)}&patient_id=4001`;
    } else if (action === "open_chat") {
      const tabChat = document.getElementById("torusTabClinicalChat");
      if (tabChat) tabChat.click();
    } else if (action === "open_appointment") {
      const apptLink = document.querySelector('.ddash-nav-item[href="#patient-appointments"]') ||
        document.querySelector('.ddash-nav-item[href="#upcoming-sessions"]');
      if (apptLink) apptLink.click();
      window.toggleTorusChatDrawer(false);
    } else if (action === "retry_email") {
      if (typeof showToastAlert === "function") {
        showToastAlert(`Opening Report ${target} for Delivery Retry...`, "info");
      }
      window.location.href = `/report-generation.html?report_id=${encodeURIComponent(target)}&patient_id=4001`;
    }
  }

  // Utility to escape HTML
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Expose initializers on window
  window.initTorusNotificationSystem = initTorusNotificationSystem;
  window.initTorusChatSystem = initTorusChatSystem;
  window.initTorusAiAssistant = initTorusAiAssistant;
  window.refreshTorusNotifications = fetchNotifications;
  window.refreshTorusChat = fetchConversations;

  // Auto-run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initTorusNotificationSystem();
      initTorusChatSystem();
      initTorusAiAssistant();
    });
  } else {
    initTorusNotificationSystem();
    initTorusChatSystem();
    initTorusAiAssistant();
  }
})();
