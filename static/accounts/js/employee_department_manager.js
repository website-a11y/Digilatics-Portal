(function () {
  function setReportingManager(managerId, managerLabel) {
    const managerSelect = document.getElementById("id_reporting_manager");
    if (!managerSelect || !managerId) {
      return;
    }

    const targetValue = String(managerId);
    let option = Array.from(managerSelect.options).find(
      (opt) => opt.value === targetValue
    );
    if (!option) {
      option = document.createElement("option");
      option.value = targetValue;
      option.text = managerLabel || "Department Manager";
      managerSelect.appendChild(option);
    }

    managerSelect.value = targetValue;
    managerSelect.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function bindDepartmentAutoManager() {
    const departmentSelect = document.getElementById("id_department");
    if (!departmentSelect) {
      return;
    }

    const managerUrl = departmentSelect.dataset.managerUrl;
    if (!managerUrl) {
      return;
    }

    departmentSelect.addEventListener("change", function () {
      const department = departmentSelect.value;
      if (!department) {
        return;
      }

      const url = new URL(managerUrl, window.location.origin);
      url.searchParams.set("department", department);

      fetch(url.toString(), {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      })
        .then((response) => response.json())
        .then((payload) => {
          if (payload && payload.manager_id) {
            setReportingManager(payload.manager_id, payload.manager_label);
          }
        })
        .catch(() => {});
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindDepartmentAutoManager);
  } else {
    bindDepartmentAutoManager();
  }
})();
