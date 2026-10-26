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
    const urlParams = new URLSearchParams(window.location.search);
    const urlRole = (urlParams.get("role") || "").toLowerCase();

    const isDoc = urlRole === "doctor" ||
      (window.currentAuthenticatedUser && window.currentAuthenticatedUser.role === "doctor") ||
      (window.currentAuthenticatedRole === "doctor") ||
      (document.getElementById("role") && document.getElementById("role").value === "doctor") ||
      (document.getElementById("docDashAvatarChip") && document.getElementById("docDashAvatarChip").textContent.trim() === "AD");

    const isViewer = urlRole === "viewer" ||
      (window.currentAuthenticatedUser && window.currentAuthenticatedUser.role === "viewer") ||
      (window.currentAuthenticatedRole === "viewer");

    if (window.currentAuthenticatedUser && window.currentAuthenticatedUser.uid) {
      return {
        uid: String(window.currentAuthenticatedUser.uid),
        role: window.currentAuthenticatedUser.role || (isDoc ? "doctor" : (isViewer ? "viewer" : "patient")),
        name: window.currentAuthenticatedUser.name || (isDoc ? "Admin Doctor" : (isViewer ? "Attender User" : "Patient User")),
        email: window.currentAuthenticatedUser.email || (isDoc ? "admin@gmail.com" : (isViewer ? "user@gmail.com" : "patient@gmail.com"))
      };
    }

    try {
      const storedDoc = sessionStorage.getItem("authenticated_doctor") || localStorage.getItem("authenticated_doctor");
      const storedPat = sessionStorage.getItem("authenticated_patient") || localStorage.getItem("authenticated_patient");
      const storedViewer = sessionStorage.getItem("authenticated_viewer") || localStorage.getItem("authenticated_viewer");
      if (isDoc && storedDoc) {
        const d = JSON.parse(storedDoc);
        return { uid: String(d.uid || "3001"), role: "doctor", name: d.name || "Admin Doctor", email: d.email || "admin@gmail.com" };
      }
      if (isViewer && storedViewer) {
        const v = JSON.parse(storedViewer);
        return { uid: String(v.uid || "6001"), role: "viewer", name: v.name || "Attender User", email: v.email || "user@gmail.com" };
      }
      if (!isDoc && !isViewer && storedPat) {
        const p = JSON.parse(storedPat);
        return { uid: String(p.uid || "4001"), role: "patient", name: p.name || "Patient User", email: p.email || "patient@gmail.com" };
      }
    } catch (_) { }

    if (isDoc) {
      return { uid: "3001", role: "doctor", name: "Admin Doctor", email: "admin@gmail.com" };
    }
    if (isViewer) {
      return { uid: "6001", role: "viewer", name: "Attender User", email: "user@gmail.com" };
    }
    return { uid: "4001", role: "patient", name: "Patient User", email: "patient@gmail.com" };
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

  // Filter and deduplicate notifications, curating a balanced, realistic sample set (Doctor: 5-6, Patient: 4-5)
  function filterAndDeduplicateNotifications(rawList) {
    if (!rawList || !rawList.length) return [];
    const user = getTorusUser();
    const isDoctor = user.role === "doctor";

    // 1. Patient Portal security: strictly filter out any notification for other patients
    let list = rawList;
    if (!isDoctor) {
      const myUid = String(user.uid || "4001").trim();
      list = rawList.filter(n => {
        const uId = String(n.user_id || "").trim();
        const rRole = String(n.role || "").trim().toLowerCase();
        return uId === myUid || uId === "all" || (uId === "" && rRole === "patient") || rRole === "all";
      });
    }

    // Identify reports that have confirmed delivery
    const deliveredReports = new Set();
    list.forEach(n => {
      const type = (n.type || "").toLowerCase();
      const rId = n.reference_id || "";
      if ((type === "report_delivered" || (n.title && n.title.toLowerCase().includes("report delivered"))) && rId) {
        deliveredReports.add(rId);
      }
    });

    const seenEventKeys = new Set();
    const seenFailureReports = new Set();
    const deduplicated = [];

    for (const notif of list) {
      const type = (notif.type || "").toLowerCase();
      const rId = notif.reference_id || "";
      const eventKey = notif.event_key || "";
      const normTitle = (notif.title || "").trim().toLowerCase();

      // Deduplicate by explicit event_key
      if (eventKey) {
        if (seenEventKeys.has(eventKey)) continue;
        seenEventKeys.add(eventKey);
      }

      // Suppress obsolete delivery failures if delivery was confirmed successful
      if (type === "email_failure" || type === "email_failed" || normTitle.includes("delivery failed")) {
        if (rId && deliveredReports.has(rId)) {
          continue;
        }
        if (rId) {
          if (seenFailureReports.has(rId)) continue;
          seenFailureReports.add(rId);
        }
      }

      deduplicated.push(notif);
    }

    // Categorize into semantic buckets to curate a realistic clinical mix:
    const buckets = {
      chat: [],
      delivery_issue: [],
      delivered: [],
      generated: [],
      appointment: [],
      system: [],
      other: []
    };

    deduplicated.forEach(n => {
      const t = (n.type || "").toLowerCase();
      const title = (n.title || "").toLowerCase();
      if (t === "chat" || t === "chat_message" || title.includes("message from")) {
        buckets.chat.push(n);
      } else if (t === "email_failure" || t === "email_failed" || title.includes("delivery failed") || title.includes("delivery issue") || title.includes("delivery notice")) {
        buckets.delivery_issue.push(n);
      } else if (t === "report_delivered" || title.includes("report delivered")) {
        buckets.delivered.push(n);
      } else if (t === "report_generated" || t === "report_available" || title.includes("report generated") || title.includes("report available")) {
        buckets.generated.push(n);
      } else if (t === "appointment" || title.includes("appointment") || title.includes("consultation") || title.includes("session")) {
        buckets.appointment.push(n);
      } else if (t === "system" || title.includes("system") || title.includes("welcome")) {
        buckets.system.push(n);
      } else {
        buckets.other.push(n);
      }
    });

    // Sort items within each bucket: unread first, then newest
    const sortBucket = (arr) => arr.sort((a, b) => {
      if (a.is_read !== b.is_read) return a.is_read - b.is_read;
      return (b.id || 0) - (a.id || 0);
    });
    Object.keys(buckets).forEach(k => sortBucket(buckets[k]));

    const curated = [];
    const addedIds = new Set();
    function addNotification(n) {
      if (!n || addedIds.has(n.id)) return;
      addedIds.add(n.id);
      curated.push(n);
    }

    if (isDoctor) {
      // Preferred sample mix for Doctor Portal: approximately 5-6 cards (strictly 4-8)
      // 1. Patient Message
      if (buckets.chat.length) addNotification(buckets.chat[0]);
      // 2. Report Delivery Failed / Issue
      if (buckets.delivery_issue.length) addNotification(buckets.delivery_issue[0]);
      // 3. Report Delivered Confirmation
      if (buckets.delivered.length) addNotification(buckets.delivered[0]);
      // 4. Diagnostic Report Generated
      if (buckets.generated.length) addNotification(buckets.generated[0]);
      // 5. Scheduled Consultation / Appointment
      if (buckets.appointment.length) addNotification(buckets.appointment[0]);
      // 6. System Calibration / Operational Notice
      if (buckets.system.length) addNotification(buckets.system[0]);

      // If fewer than 5, backfill from remaining deduplicated list up to 6
      if (curated.length < 5) {
        for (const n of deduplicated) {
          if (curated.length >= 6) break;
          addNotification(n);
        }
      }
    } else {
      // Preferred sample mix for Patient Portal: approximately 4-5 cards (strictly 3-7)
      // 1. Message from Attending Doctor
      if (buckets.chat.length) addNotification(buckets.chat[0]);
      // 2. Diagnostic Report Available
      if (buckets.generated.length) addNotification(buckets.generated[0]);
      // 3. Report Delivery Status Notice / Confirmation
      if (buckets.delivered.length) addNotification(buckets.delivered[0]);
      else if (buckets.delivery_issue.length) addNotification(buckets.delivery_issue[0]);
      // 4. Upcoming Consultation Reminder
      if (buckets.appointment.length) addNotification(buckets.appointment[0]);
      // 5. Welcome / Care Team Notice
      if (buckets.system.length) addNotification(buckets.system[0]);

      // If fewer than 4, backfill from remaining patient items up to 5
      if (curated.length < 4) {
        for (const n of deduplicated) {
          if (curated.length >= 5) break;
          addNotification(n);
        }
      }
    }

    // Sort curated list: unread first, then newest
    curated.sort((a, b) => {
      if (a.is_read !== b.is_read) return a.is_read - b.is_read;
      return (b.id || 0) - (a.id || 0);
    });

    const maxLimit = isDoctor ? 8 : 7;
    return curated.slice(0, maxLimit);
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
    const chatSendBtn = document.getElementById("torusChatSendBtn");
    if (chatInput) {
      chatInput.addEventListener("input", function () {
        if (chatSendBtn) {
          chatSendBtn.disabled = !this.value.trim() || isSendingMessage;
        }
      });
      chatInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (this.value.trim() && !isSendingMessage) {
            sendChatMessage();
          }
        }
      });
    }

    // Initial check for unread chat messages & periodic background badge updates
    fetchConversations(false);
    setInterval(() => {
      if (!isChatDrawerOpen) {
        fetchConversations(false);
      }
    }, 6000);
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
      }, 3000);
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
      let otherName = "";
      if (user.role === "doctor") {
        otherName = c.patient_name ? `${c.patient_name} (${c.patient_id})` : `Patient ${c.patient_id}`;
      } else if (user.role === "viewer") {
        otherName = `${c.doctor_name || "Dr. Admin Doctor"} (${c.patient_name || "Patient"})`;
      } else {
        otherName = c.doctor_name || `Dr. ${c.doctor_id}`;
      }
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
      if (user.role === "doctor") {
        recipientLabel.textContent = `${currentConv.patient_name || "Patient"} (${currentConv.patient_id})`;
      } else if (user.role === "viewer") {
        recipientLabel.textContent = `${currentConv.doctor_name || "Dr. Admin Doctor"} (Attender)`;
      } else {
        recipientLabel.textContent = currentConv.doctor_name || "Dr. Admin Doctor";
      }
    }

    const statusDot = document.getElementById("torusChatStatusDot");
    if (statusDot) {
      statusDot.style.display = "inline-block";
      statusDot.title = "Connected • Secure Clinical Messaging Channel";
    }
  }

  function loadConversationMessages(convId, autoScroll = true) {
    if (!convId) return;
    const user = getTorusUser();
    const listEl = document.getElementById("torusChatMessagesList");

    fetch(`/api/conversations/${encodeURIComponent(convId)}/messages?user_id=${encodeURIComponent(user.uid)}&role=${encodeURIComponent(user.role)}`)
      .then(res => {
        if (res.status === 403) {
          if (listEl) {
            listEl.innerHTML = `
              <div class="torus-chat-feed-empty" style="color: #f87171;">
                <div class="torus-chat-feed-empty-icon">🔒</div>
                <div>Unauthorized: You do not have permission to view this patient conversation.</div>
              </div>
            `;
          }
          return null;
        }
        return res.json();
      })
      .then(data => {
        if (data && data.success) {
          renderMessagesList(data.messages || [], autoScroll);
          if (isChatDrawerOpen) {
            // Mark conversation as read whenever chat is actively open
            fetch(`/api/conversations/${encodeURIComponent(convId)}/read`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reader_id: user.uid, user_id: user.uid })
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
    const wasNearBottom = (listEl.scrollHeight - listEl.scrollTop - listEl.clientHeight) < 70;

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
      const isMine = String(msg.sender_id) === String(user.uid) || (msg.sender_role === user.role && (!msg.sender_id || !user.uid));
      const timeStr = formatMessageTime(msg.created_at);
      const isRead = Boolean(msg.is_read);
      const statusIcon = isRead
        ? `<span class="torus-message-status status-read" title="Read (✓✓)">✓✓</span>`
        : `<span class="torus-message-status" title="Delivered (✓✓)">✓✓</span>`;

      const otherDisplayName = msg.sender_name || (msg.sender_role === "doctor" ? "Dr. Admin Doctor" : "Patient User");

      html += `
        <div class="torus-message-row ${isMine ? "outgoing" : "incoming"}">
          <div class="torus-message-bubble ${isMine ? "bubble-mine" : "bubble-theirs"}">
            ${!isMine ? `<div class="torus-message-sender-name">${escapeHtml(otherDisplayName)}</div>` : ""}
            <div class="torus-message-text">${escapeHtml(msg.content)}</div>
            <div class="torus-message-meta">
              <span class="torus-message-time">${timeStr}</span>
              ${isMine ? statusIcon : ""}
            </div>
          </div>
        </div>
      `;
    });

    listEl.innerHTML = html;

    if (autoScroll || wasNearBottom) {
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
    const listEl = document.getElementById("torusChatMessagesList");
    if (!input || !currentActiveConvId) return;

    const text = input.value.trim();
    if (!text) return;

    const user = getTorusUser();
    isSendingMessage = true;
    if (sendBtn) sendBtn.disabled = true;

    // Optimistic pending message bubble for immediate user feedback
    const tempId = "torusMsgSending_" + Date.now();
    if (listEl) {
      const nowTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const pendingRow = document.createElement("div");
      pendingRow.className = "torus-message-row outgoing torus-message-pending";
      pendingRow.id = tempId;
      pendingRow.innerHTML = `
        <div class="torus-message-bubble bubble-mine" style="opacity: 0.88;">
          <div class="torus-message-text">${escapeHtml(text)}</div>
          <div class="torus-message-meta">
            <span class="torus-message-time">${nowTime}</span>
            <span class="torus-message-status" title="Sending...">⏳</span>
          </div>
        </div>
      `;
      listEl.appendChild(pendingRow);
      listEl.scrollTop = listEl.scrollHeight;
    }

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
        const pendingEl = document.getElementById(tempId);
        if (pendingEl) pendingEl.remove();

        if (data && data.success) {
          input.value = "";
          if (sendBtn) sendBtn.disabled = true;
          loadConversationMessages(currentActiveConvId, true);
        } else {
          if (sendBtn) sendBtn.disabled = !input.value.trim();
          alert("Failed to send message: " + (data?.error || "Unknown error"));
        }
      })
      .catch(err => {
        isSendingMessage = false;
        const pendingEl = document.getElementById(tempId);
        if (pendingEl) pendingEl.remove();
        if (sendBtn) sendBtn.disabled = !input.value.trim();
        console.error("[Chat] Send error:", err);
        alert("Failed to send message due to network error. Your unsent message is preserved so you can retry.");
      });
  }

  // =========================================================================
  // 3. AI SUPPORT ASSISTANT
  // =========================================================================

  let currentAiConversationId = sessionStorage.getItem("torus_ai_conv_id") || localStorage.getItem("torus_ai_conv_id") || "";

  function getAiConversationId() {
    if (!currentAiConversationId) {
      const u = getTorusUser();
      currentAiConversationId = `ai_conv_${u.uid}_${Date.now()}`;
      try {
        sessionStorage.setItem("torus_ai_conv_id", currentAiConversationId);
      } catch (_) { }
    }
    return currentAiConversationId;
  }

  function initTorusAiAssistant() {
    const aiForm = document.getElementById("torusAiForm");
    const aiInput = document.getElementById("torusAiMessageInput");
    const aiSendBtn = document.getElementById("torusAiSendBtn");

    if (aiForm) {
      aiForm.onsubmit = function (e) {
        e.preventDefault();
        sendAiQuery();
      };
    }

    if (aiInput) {
      aiInput.oninput = function () {
        if (aiSendBtn) {
          aiSendBtn.disabled = !this.value.trim() || isAiQuerying;
        }
      };
      aiInput.onkeydown = function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (this.value.trim() && !isAiQuerying) {
            sendAiQuery();
          }
        }
      };
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
        btn.onclick = function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (isAiQuerying) return;
          const q = this.getAttribute("data-query") || this.textContent;
          if (q && q.trim()) sendAiQuery(q.trim());
        };
      });
    }

    if (feed && feed.children.length === 0) {
      const convId = getAiConversationId();
      // Try to restore previous session history
      fetch(`/api/ai-assistant/history?conversationId=${encodeURIComponent(convId)}&user_id=${encodeURIComponent(user.uid)}&role=${encodeURIComponent(user.role)}`)
        .then(res => res.json())
        .then(data => {
          if (data && data.success && Array.isArray(data.messages) && data.messages.length > 0) {
            feed.innerHTML = "";
            data.messages.forEach(m => {
              if (m.role === "user") {
                feed.innerHTML += `
                  <div class="torus-message-row outgoing">
                    <div class="torus-message-bubble bubble-mine">
                      <div class="torus-message-text">${escapeHtml(m.content)}</div>
                      <div class="torus-message-meta"><span class="torus-message-time">${formatTimeAgo(m.created_at)}</span></div>
                    </div>
                  </div>
                `;
              } else {
                feed.innerHTML += `
                  <div class="torus-message-row incoming">
                    <div class="torus-message-bubble bubble-ai">
                      <div class="torus-ai-badge">🤖 TORUS AI Support Assistant</div>
                      <div class="torus-message-text">${formatAiResponse(m.content)}</div>
                      <div class="torus-ai-disclaimer">TORUS Clinical Telemetry • Non-clinical guidance</div>
                    </div>
                  </div>
                `;
              }
            });
            feed.scrollTop = feed.scrollHeight;
          } else {
            renderAiDefaultWelcome(feed, user);
          }
        })
        .catch(() => renderAiDefaultWelcome(feed, user));
    }
  }

  function renderAiDefaultWelcome(feed, user) {
    if (!feed || feed.children.length > 0) return;
    feed.innerHTML = `
      <div class="torus-message-row incoming">
        <div class="torus-message-bubble bubble-ai">
          <div class="torus-ai-badge">🤖 TORUS AI Support Assistant</div>
          <div class="torus-message-text">
            Hello ${escapeHtml(user.name)}! I'm the TORUS AI Support Assistant.
            <br/><br/>
            I can answer conversational questions, explain machine learning and medical workflows, and look up verified diagnostic reports, delivery statuses, and upcoming appointments.
            <br/><br/>
            How can I help you today?
          </div>
          <div class="torus-ai-disclaimer">Non-clinical guidance. For medical decisions, consult qualified clinicians.</div>
        </div>
      </div>
    `;
  }

  function formatAiResponse(text) {
    if (!text) return "";
    let escaped = escapeHtml(text);
    escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    escaped = escaped.replace(/(^|[^\*])\*([^\*]+)\*([^\*]|$)/g, '$1<em>$2</em>$3');
    escaped = escaped.replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.08); padding: 1px 4px; border-radius: 4px; color: #38bdf8;">$1</code>');
    escaped = escaped.replace(/\n/g, '<br/>');
    return escaped;
  }

  function sendAiQuery(customQuery, isRetry = false) {
    if (isAiQuerying) return;
    const input = document.getElementById("torusAiMessageInput");
    const sendBtn = document.getElementById("torusAiSendBtn");
    const feed = document.getElementById("torusAiMessagesList");
    if (!feed) return;

    const rawQuery = typeof customQuery === "string" && customQuery.trim()
      ? customQuery.trim()
      : (input ? input.value.trim() : "");

    if (!rawQuery) {
      if (input) input.focus();
      return;
    }

    const query = rawQuery;
    const user = getTorusUser();
    const convId = getAiConversationId();

    isAiQuerying = true;
    if (sendBtn) sendBtn.disabled = true;
    if (input) input.value = "";

    // Append user query bubble if not a retry
    if (!isRetry) {
      feed.innerHTML += `
        <div class="torus-message-row outgoing">
          <div class="torus-message-bubble bubble-mine">
            <div class="torus-message-text">${escapeHtml(query)}</div>
            <div class="torus-message-meta"><span class="torus-message-time">Just now</span></div>
          </div>
        </div>
      `;
    }

    // Append thinking bubble
    const thinkingId = "aiThinking_" + Date.now();
    feed.innerHTML += `
      <div class="torus-message-row incoming" id="${thinkingId}">
        <div class="torus-message-bubble bubble-ai">
          <div class="torus-ai-thinking">
            <span></span><span></span><span></span> Checking TORUS records &amp; thinking...
          </div>
        </div>
      </div>
    `;

    feed.scrollTop = feed.scrollHeight;

    const payload = {
      question: query,
      query: query,
      message: query,
      conversationId: convId,
      conversation_id: convId,
      user_id: user.uid,
      role: user.role
    };

    fetch("/api/ai-assistant/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(res => {
        if (!res.ok && res.status === 404) {
          // Fallback to legacy endpoint if /api/ai-assistant/chat not mapped
          return fetch("/api/ai/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          }).then(r => r.json());
        }
        return res.json();
      })
      .then(data => {
        isAiQuerying = false;
        if (sendBtn) sendBtn.disabled = !(input && input.value.trim());
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();

        if (data && data.success) {
          if (data.conversationId) {
            currentAiConversationId = data.conversationId;
            try { sessionStorage.setItem("torus_ai_conv_id", data.conversationId); } catch (_) { }
          }

          const answerText = data.answer || data.response || (data.message && data.message.content) || "";
          const actionsHtml = (data.suggested_actions || []).map(act => `
            <button type="button" class="torus-ai-action-btn" data-action="${escapeHtml(act.action || '')}" data-target="${escapeHtml(act.target || act.url || act.query || '')}">
              ${escapeHtml(act.label)} &rarr;
            </button>
          `).join("");

          const badgeTitle = data.is_ai ? "🤖 TORUS AI Support Assistant" : "🤖 TORUS AI Support • Operational Assistant";

          feed.innerHTML += `
            <div class="torus-message-row incoming">
              <div class="torus-message-bubble bubble-ai">
                <div class="torus-ai-badge">${badgeTitle}</div>
                <div class="torus-message-text">${formatAiResponse(answerText)}</div>
                ${actionsHtml ? `<div class="torus-ai-actions-wrap">${actionsHtml}</div>` : ""}
                <div class="torus-ai-feedback">
                  <span class="torus-ai-feedback-text">Was this helpful?</span>
                  <button type="button" class="torus-ai-thumb-btn" onclick="this.classList.toggle('active'); this.parentElement.querySelector('.torus-ai-feedback-text').textContent='Thanks for your feedback!';" title="Helpful">👍</button>
                  <button type="button" class="torus-ai-thumb-btn" onclick="this.classList.toggle('active'); this.parentElement.querySelector('.torus-ai-feedback-text').textContent='Thanks for your feedback!';" title="Not helpful">👎</button>
                </div>
                <div class="torus-ai-disclaimer">${escapeHtml(data.disclaimer || "TORUS Tele-Ultrasound • Non-clinical guidance")}</div>
              </div>
            </div>
          `;

          // Bind suggested actions
          feed.querySelectorAll(".torus-ai-action-btn").forEach(actBtn => {
            actBtn.onclick = function () {
              const act = this.getAttribute("data-action");
              const target = this.getAttribute("data-target");
              executeAiAction(act, target);
            };
          });

          feed.scrollTop = feed.scrollHeight;
        } else {
          const errText = (data?.error && typeof data.error === 'object' ? data.error.message : data?.error) || "The AI assistant is temporarily unavailable.";
          feed.innerHTML += `
            <div class="torus-message-row incoming">
              <div class="torus-message-bubble bubble-ai" style="border-color: rgba(248, 113, 113, 0.4);">
                <div class="torus-message-text" style="color: #fca5a5;">
                  ${escapeHtml(errText)}
                </div>
                <button type="button" class="torus-ai-retry-btn" data-query="${escapeHtml(query)}" style="margin-top: 8px; background: rgba(248, 113, 113, 0.15); border: 1px solid rgba(248, 113, 113, 0.4); color: #fca5a5; border-radius: 6px; padding: 4px 10px; font-size: 11px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                  ↻ Retry Question
                </button>
              </div>
            </div>
          `;
          feed.querySelectorAll(".torus-ai-retry-btn").forEach(retryBtn => {
            retryBtn.onclick = function () {
              const q = this.getAttribute("data-query");
              this.closest(".torus-message-row").remove();
              sendAiQuery(q, true);
            };
          });
          feed.scrollTop = feed.scrollHeight;
        }
      })
      .catch(err => {
        isAiQuerying = false;
        if (sendBtn) sendBtn.disabled = !(input && input.value.trim());
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();
        console.error("[AI] Chat error:", err);
        feed.innerHTML += `
          <div class="torus-message-row incoming">
            <div class="torus-message-bubble bubble-ai" style="border-color: rgba(248, 113, 113, 0.4);">
              <div class="torus-message-text" style="color: #fca5a5;">
                Unable to connect to the AI Support service. Please check network connection and try again.
              </div>
              <button type="button" class="torus-ai-retry-btn" data-query="${escapeHtml(query)}" style="margin-top: 8px; background: rgba(248, 113, 113, 0.15); border: 1px solid rgba(248, 113, 113, 0.4); color: #fca5a5; border-radius: 6px; padding: 4px 10px; font-size: 11px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                ↻ Retry Question
              </button>
            </div>
          </div>
        `;
        feed.querySelectorAll(".torus-ai-retry-btn").forEach(retryBtn => {
          retryBtn.onclick = function () {
            const q = this.getAttribute("data-query");
            this.closest(".torus-message-row").remove();
            sendAiQuery(q, true);
          };
        });
        feed.scrollTop = feed.scrollHeight;
      });
  }

  function executeAiAction(action, target) {
    if (action === "query") {
      sendAiQuery(target);
    } else if (action === "view_report") {
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
    } else if (action === "navigate") {
      if (target) window.location.href = target;
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
