// ---------------------------------------------------------------------------
// Site-wide settings. This is the one file to edit for contact details,
// affiliation and social links — everything else on the site reads from
// here rather than hard-coding it in a page or component.
// ---------------------------------------------------------------------------

export const site = {
  name: 'Cenk Celik',
  role: 'Research Fellow',
  institution: 'University College London',
  lab: 'Secrier Lab',
  labUrl: 'https://secrierlab.github.io',
  department: 'UCL Genetics Institute',
  address: ['Darwin Building', 'Gower Street', 'WC1E 6BT London, UK'],
  email: 'cenk.celik@proton.me',
  url: 'https://cenk-celik.github.io',
  description:
    'Research Fellow at UCL studying cellular quiescence, tumour plasticity and the tumour microenvironment using single-cell and spatial transcriptomics.',

  // Academic identifiers / socials — the only ones that should ever
  // appear as icons are listed in `socials` below, in display order.
  orcid: '0000-0001-8301-0172',
  scholarId: 'zidMl6YAAAAJ',
  githubUsername: 'cenk-celik',

  socials: [
    {
      label: 'Google Scholar',
      href: 'https://scholar.google.com/citations?user=zidMl6YAAAAJ',
      icon: 'scholar',
    },
    {
      label: 'Bluesky',
      href: 'https://bsky.app/profile/cenkcelik.bsky.social',
      icon: 'bluesky',
    },
    {
      label: 'LinkedIn',
      href: 'https://www.linkedin.com/in/cenk-celik',
      icon: 'linkedin',
    },
    {
      label: 'X (Twitter)',
      href: 'https://twitter.com/_cenk',
      icon: 'x',
    },
    {
      label: 'ORCID',
      href: 'https://orcid.org/0000-0001-8301-0172',
      icon: 'orcid',
    },
  ],

  nav: [
    { label: 'Research', href: '/research' },
    { label: 'Publications', href: '/publications' },
    { label: 'Teaching', href: '/teaching' },
    { label: 'Software', href: '/software' },
    { label: 'News', href: '/news' },
  ],

  bluesky: {
    handle: 'cenkcelik.bsky.social',
  },

  cvPdf: '/cv.pdf',
} as const;
