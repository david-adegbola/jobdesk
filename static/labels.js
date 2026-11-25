// Names for the job details stored as codes (core/jobmeta.py). English and Finnish; the pages use English
// for now, and the Finnish names are ready for the language switch.
export const LABELS = {
  level: {
    thesis: ["Thesis", "Opinnäytetyö"],
    internship: ["Internship", "Harjoittelu"],
    trainee: ["Trainee programme", "Trainee-ohjelma"],
    entry: ["Entry level", "Aloitustason työ"],
    experienced: ["Experienced", "Kokeneelle"],
  },
  employment: {
    summer: ["Summer job", "Kesätyö"],
    full_time: ["Full-time", "Kokoaikainen"],
    part_time: ["Part-time", "Osa-aikainen"],
    fixed_term: ["Fixed-term", "Määräaikainen"],
    permanent: ["Permanent", "Vakituinen"],
    apprenticeship: ["Apprenticeship", "Oppisopimus"],
    gig: ["Gig work", "Keikkatyö"],
  },
  mode: {
    onsite: ["On site", "Lähityö"],
    hybrid: ["Hybrid", "Hybridi"],
    remote: ["Remote", "Etätyö"],
  },
  permit: {
    citizenship: ["Finnish citizenship required", "Edellyttää Suomen kansalaisuutta"],
    security_clearance: ["Security clearance", "Turvallisuusselvitys"],
    eu_eea: ["EU/EEA right to work", "EU/ETA-työskentelyoikeus"],
    right_to_work: ["Needs the right to work in Finland", "Edellyttää työskentelyoikeutta Suomessa"],
    sponsorship: ["Visa or permit support offered", "Tukea työ- tai oleskelulupaan"],
  },
  sector: {
    public: ["Public sector", "Julkinen sektori"],
    private: ["Private company", "Yksityinen yritys"],
    third: ["Non-profit", "Järjestö tai säätiö"],
  },
  language: {
    required: ["required", "vaaditaan"],
    preferred: ["an advantage", "eduksi"],
    not_needed: ["not required", "ei vaadita"],
    unclear: ["not mentioned", "ei mainittu"],
  },
  period: {
    hour: ["/ hour", "/ tunti"],
    month: ["/ month", "/ kk"],
    year: ["/ year", "/ vuosi"],
  },
};

export const label = (group, code, lang = 0) => (LABELS[group]?.[code] || [code, code])[lang];

const euro = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

// "€2,800–3,200 / month", or "" when the ad gives no pay
export function salaryText(job) {
  if (job.salary_min == null) return "";
  const range = job.salary_max && job.salary_max !== job.salary_min
    ? `€${euro.format(job.salary_min)}–${euro.format(job.salary_max)}` : `€${euro.format(job.salary_min)}`;
  return `${range} ${label("period", job.salary_period)}`.trim();
}
