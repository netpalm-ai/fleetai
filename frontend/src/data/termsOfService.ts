export type TermsSection = {
  heading: string;
  body: string[];
};

export const TERMS_TITLE = "FleetAI Terms of Service";
export const TERMS_UPDATED = "11 November 2026";

export const TERMS_SECTIONS: TermsSection[] = [
  {
    heading: "1. Agreement",
    body: [
      "These Terms of Service (the “Terms”) govern access to and use of FleetAI, including the web application, API, and any related tooling (together, the “Service”). By creating an account or using the Service, you agree to these Terms.",
      "If you use FleetAI on behalf of an organization, you represent that you have authority to bind that organization, and “you” includes that organization.",
    ],
  },
  {
    heading: "2. The Service",
    body: [
      "FleetAI is a ticket runner. It can parse reports, propose engineering work against a customer product checkout, and record verify and complete outcomes. The Service does not replace your own code review, security review, or production change process.",
      "We may change features, limits, or availability. We will not use the Service to deploy your product unless you separately instruct a human operator to do so.",
    ],
  },
  {
    heading: "3. Accounts",
    body: [
      "You must provide an accurate email and keep credentials confidential. You are responsible for activity under your account.",
      "We may suspend or close an account that is shared in an unsafe way, that attempts to bypass access controls, or that we reasonably believe is being used to harm the Service or another customer.",
    ],
  },
  {
    heading: "4. Customer software and data",
    body: [
      "You retain rights in the product checkouts, tickets, emails, and documents you provide. You grant us a limited license to process that material solely to operate the Service for you.",
      "Do not upload material you are not allowed to share. Do not paste secrets, credentials, or regulated clinical or personal data into tickets, prompts, or run logs unless your organization has a written process that allows it.",
    ],
  },
  {
    heading: "5. Acceptable use",
    body: [
      "You may not probe, scrape, or disrupt the Service; use it to attack other systems; reverse engineer except where the law allows; or misrepresent the origin of model output as unaided human work when your organization requires disclosure.",
      "Automated agents that call the API must use the credentials issued to you and must not exceed rate limits we publish or communicate.",
    ],
  },
  {
    heading: "6. Models and third parties",
    body: [
      "Parse, summary, solve, and verify steps may call third-party or local models (for example Bedrock, Cursor, or Ollama) using keys and hosts you configure. Their terms apply to those calls.",
      "Model output can be wrong, incomplete, or unsafe to merge. You must review diffs, tests, and production impact before you accept a change.",
    ],
  },
  {
    heading: "7. Confidentiality",
    body: [
      "Each party will protect the other’s non-public information with reasonable care and use it only to perform under these Terms.",
      "This does not restrict information that is public, independently developed, or required to be disclosed by law, provided the receiving party gives notice where legally permitted.",
    ],
  },
  {
    heading: "8. Intellectual property",
    body: [
      "FleetAI, its interface, and documentation remain ours or our licensors’. These Terms do not sell the software.",
      "Feedback you give may be used to improve the Service without obligation to you.",
    ],
  },
  {
    heading: "9. Disclaimer",
    body: [
      "The Service is provided “as is.” We disclaim warranties of merchantability, fitness for a particular purpose, and non-infringement, to the extent the law allows.",
      "We do not warrant that tickets will be complete, that a solver run will compile, or that a verify verdict matches production.",
    ],
  },
  {
    heading: "10. Limitation of liability",
    body: [
      "To the extent the law allows, neither party is liable for indirect, incidental, special, consequential, or lost-profit damages, or for lost data, even if advised of the possibility.",
      "Our total liability for claims arising out of the Service in any twelve-month period is limited to the fees you paid for the Service in that period, or one hundred US dollars if you paid none.",
    ],
  },
  {
    heading: "11. Indemnity",
    body: [
      "You will defend and indemnify us against claims arising from your content, your product checkouts, or your misuse of the Service, including reasonable legal fees.",
    ],
  },
  {
    heading: "12. Term",
    body: [
      "These Terms start when you first create an account or use the Service and continue until you close the account or we stop providing the Service to you.",
      "Sections that by their nature should survive (including confidentiality, IP, disclaimer, liability, and indemnity) survive termination.",
    ],
  },
  {
    heading: "13. Changes",
    body: [
      "We may update these Terms. The date at the top of this page is the current version. Continued use after an update is acceptance of the new Terms. If you do not agree, stop using the Service and close your account.",
    ],
  },
  {
    heading: "14. Contact",
    body: [
      "Questions about these Terms can be sent to the operator of your FleetAI deployment. This document is mock contract text for the product UI and is not legal advice.",
    ],
  },
];
