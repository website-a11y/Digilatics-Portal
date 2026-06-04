(function () {
  function asNumber(value) {
    if (!value) return 0;
    var cleaned = String(value).replace(/,/g, '').trim();
    var n = parseFloat(cleaned);
    return isNaN(n) ? 0 : n;
  }

  function setAmount(input, value) {
    if (!input) return;
    input.value = value.toFixed(2);
  }

  function formatMoney(n) {
    return Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function getValue(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback || '';
    return el.value || fallback || '';
  }

  function calculateFromForm() {
    var gross = asNumber(getValue('id_gross_salary_input', '0'));
    var basic = asNumber(getValue('id_basic_salary', '0'));
    var house = asNumber(getValue('id_house_rent_allowance', '0'));
    var utility = asNumber(getValue('id_utility_allowance', '0'));
    var medical = asNumber(getValue('id_medical_allowance', '0'));

    var monthlyTaxable = gross * 0.9;
    var annualTaxable = monthlyTaxable * 12;
    var annualTax = 0;
    if (annualTaxable <= 600000) annualTax = 0;
    else if (annualTaxable <= 1200000) annualTax = (annualTaxable - 600000) * 0.01;
    else if (annualTaxable <= 2200000) annualTax = 6000 + (annualTaxable - 1200000) * 0.11;
    else if (annualTaxable <= 3200000) annualTax = 116000 + (annualTaxable - 2200000) * 0.23;
    else if (annualTaxable <= 4100000) annualTax = 345000 + (annualTaxable - 3200000) * 0.30;
    else annualTax = 615000 + (annualTaxable - 4100000) * 0.35;
    var monthlyTax = annualTax / 12;

    var workingDays = asNumber(getValue('id_total_working_days', '0'));
    var unpaidDays = asNumber(getValue('id_unpaid_days', '0'));
    var attendance = (workingDays > 0) ? ((gross / workingDays) * unpaidDays) : 0;

    var loanAdvance = asNumber(getValue('id_loan_installment', '0')) + asNumber(getValue('id_advance_salary_repayment', '0'));
    var statutory = asNumber(getValue('id_eobi_contribution', '0')) + asNumber(getValue('id_pessi_contribution', '0'));
    var benefits = asNumber(getValue('id_gratuity_deduction', '0')) + asNumber(getValue('id_provident_fund_deduction', '0')) + asNumber(getValue('id_misc_deduction', '0'));
    var totalDed = monthlyTax + attendance + loanAdvance + statutory + benefits;
    var net = gross - totalDed;

    return {
      gross: gross,
      basic: basic,
      house: house,
      utility: utility,
      medical: medical,
      monthlyTaxable: monthlyTaxable,
      annualTaxable: annualTaxable,
      annualTax: annualTax,
      monthlyTax: monthlyTax,
      attendance: attendance,
      loanAdvance: loanAdvance,
      statutory: statutory,
      benefits: benefits,
      totalDed: totalDed,
      net: net
    };
  }

  function buildLiveSlipHtml() {
    var c = calculateFromForm();
    return '' +
      '<div class="salary-slip-sheet">' +
      '<div class="salary-slip-title">Salary Slip Preview</div>' +
      '<table class="salary-slip-table">' +
      '<tr><th>Gross Salary</th><td>PKR ' + formatMoney(c.gross) + '</td><th>Monthly Taxable (90%)</th><td>PKR ' + formatMoney(c.monthlyTaxable) + '</td></tr>' +
      '<tr><th>Basic (60%)</th><td>PKR ' + formatMoney(c.basic) + '</td><th>House Rent (20%)</th><td>PKR ' + formatMoney(c.house) + '</td></tr>' +
      '<tr><th>Utility (10%)</th><td>PKR ' + formatMoney(c.utility) + '</td><th>Medical (10% Exempt)</th><td>PKR ' + formatMoney(c.medical) + '</td></tr>' +
      '<tr><th>Annual Taxable</th><td>PKR ' + formatMoney(c.annualTaxable) + '</td><th>Annual Tax</th><td>PKR ' + formatMoney(c.annualTax) + '</td></tr>' +
      '<tr><th>Monthly Tax</th><td>PKR ' + formatMoney(c.monthlyTax) + '</td><th>Attendance Deduction</th><td>PKR ' + formatMoney(c.attendance) + '</td></tr>' +
      '<tr><th>Loan + Advance</th><td>PKR ' + formatMoney(c.loanAdvance) + '</td><th>EOBI + PESSI</th><td>PKR ' + formatMoney(c.statutory) + '</td></tr>' +
      '<tr><th>Gratuity + PF + Misc</th><td>PKR ' + formatMoney(c.benefits) + '</td><th>Total Deductions</th><td>PKR ' + formatMoney(c.totalDed) + '</td></tr>' +
      '<tr><th>Net Salary</th><td colspan="3"><strong>PKR ' + formatMoney(c.net) + '</strong></td></tr>' +
      '</table>' +
      '</div>';
  }

  function updateLivePreview() {
    var preview = document.getElementById('salary-slip-live-preview');
    if (!preview) return;
    var c = calculateFromForm();
    if (c.gross <= 0) {
      preview.innerHTML = 'Enter Gross Salary and deductions to view preview.';
      return;
    }
    preview.innerHTML = 'Gross: PKR ' + formatMoney(c.gross) + ' | Tax: PKR ' + formatMoney(c.monthlyTax) + ' | Net: PKR ' + formatMoney(c.net);
  }

  function bindAutoFill() {
    var gross = document.getElementById('id_gross_salary_input');
    var basic = document.getElementById('id_basic_salary');
    var house = document.getElementById('id_house_rent_allowance');
    var utility = document.getElementById('id_utility_allowance');
    var medical = document.getElementById('id_medical_allowance');
    if (!gross || !basic || !house || !utility || !medical) return;

    ensurePreviewUi(gross);

    function applyAuto() {
      var g = asNumber(gross.value);
      if (g > 0) {
        setAmount(basic, g * 0.60);
        setAmount(house, g * 0.20);
        setAmount(utility, g * 0.10);
        setAmount(medical, g * 0.10);
      }
      updateLivePreview();
    }

    gross.addEventListener('input', applyAuto);
    gross.addEventListener('change', applyAuto);

    var watchIds = [
      'id_total_working_days', 'id_unpaid_days', 'id_loan_installment', 'id_advance_salary_repayment',
      'id_eobi_contribution', 'id_pessi_contribution', 'id_gratuity_deduction', 'id_provident_fund_deduction',
      'id_misc_deduction', 'id_basic_salary', 'id_house_rent_allowance', 'id_utility_allowance', 'id_medical_allowance'
    ];
    watchIds.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', updateLivePreview);
      el.addEventListener('change', updateLivePreview);
    });

    applyAuto();
  }

  function bindModal() {
    var btn = document.getElementById('salary-slip-preview-btn');
    var modal = document.getElementById('salary-slip-modal');
    var closeBtn = document.getElementById('salary-slip-modal-close');
    var backdrop = modal ? modal.querySelector('.salary-slip-modal__backdrop') : null;
    var content = document.getElementById('salary-slip-modal-content');
    var serverTemplate = document.getElementById('salary-slip-server-template');
    if (!btn || !modal || !content) return;

    function openModal() {
      var serverHtml = serverTemplate ? serverTemplate.innerHTML.trim() : '';
      content.innerHTML = serverHtml || buildLiveSlipHtml();
      modal.setAttribute('aria-hidden', 'false');
      document.body.classList.add('salary-slip-modal-open');
    }

    function closeModal() {
      modal.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('salary-slip-modal-open');
    }

    btn.addEventListener('click', openModal);
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (backdrop) backdrop.addEventListener('click', closeModal);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.getAttribute('aria-hidden') === 'false') closeModal();
    });
  }

  function init() {
    bindAutoFill();
    bindModal();
  }

  function ensurePreviewUi(grossInputEl) {
    if (document.getElementById('salary-slip-preview-btn')) return;
    var row = grossInputEl.closest('.form-row') || grossInputEl.closest('.fieldBox') || grossInputEl.parentElement;
    if (!row || !row.parentElement) return;

    var wrap = document.createElement('div');
    wrap.className = 'salary-preview-inline';
    wrap.innerHTML =
      '<button type=\"button\" id=\"salary-slip-preview-btn\" class=\"salary-preview-btn\">Preview Salary Slip</button>' +
      '<div id=\"salary-slip-live-preview\" style=\"margin-top:8px;color:#666;\">Enter Gross Salary and deductions to view preview.</div>' +
      '<div id=\"salary-slip-server-template\" style=\"display:none;\"></div>' +
      '<div id=\"salary-slip-modal\" class=\"salary-slip-modal\" aria-hidden=\"true\">' +
      '<div class=\"salary-slip-modal__backdrop\"></div>' +
      '<div class=\"salary-slip-modal__dialog\">' +
      '<div class=\"salary-slip-modal__header\"><strong>Salary Slip Preview</strong><button type=\"button\" id=\"salary-slip-modal-close\" class=\"salary-slip-modal__close\">x</button></div>' +
      '<div id=\"salary-slip-modal-content\" class=\"salary-slip-modal__content\"></div>' +
      '</div></div>';
    row.parentElement.insertBefore(wrap, row.nextSibling);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
