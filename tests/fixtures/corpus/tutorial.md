# Build Your First GitHub Actions CI Pipeline for a Node.js Project

*A friendly, step-by-step walkthrough from an empty repo to a green checkmark.*

---

If you've ever pushed code, crossed your fingers, and hoped you didn't break anything, this post is for you. Today we're setting up **continuous integration (CI)** with GitHub Actions. By the end, every push and pull request will automatically:

- install your dependencies,
- run your tests on more than one Node.js version,
- reuse cached packages so builds stay fast, and
- show off a shiny status badge in your README.

No prior CI experience needed. If you can run `npm test` on your laptop, you can do this.

## What You'll Need

Before we start, make sure you have:

1. A [GitHub](https://github.com) account
2. [Git](https://git-scm.com/) installed locally
3. [Node.js](https://nodejs.org/) (an LTS version is perfect) and npm
4. About 20 minutes and a beverage of your choice ☕

> **Tip:** Run `node --version` and `git --version` in your terminal to confirm everything is installed.

## Step 1: Create an Empty Repository

Head over to GitHub and click **New repository**. Call it something like `hello-ci`, leave it public, and **don't** add a README yet (we'll make our own).

Now clone it locally:

```bash
git clone https://github.com/<your-username>/hello-ci.git
cd hello-ci
```

You now have a beautifully empty folder. Let's fill it.

## Step 2: Set Up a Tiny Node.js Project

Initialize a `package.json`:

```bash
npm init -y
```

Next, we need some code worth testing. Create a file called `math.js`:

```javascript
// math.js
function add(a, b) {
  return a + b;
}

function multiply(a, b) {
  return a * b;
}

module.exports = { add, multiply };
```

Nothing fancy, but it gives us something real to check.

## Step 3: Add Tests

We'll use [Jest](https://jestjs.io/) because it's popular and needs almost no configuration:

```bash
npm install --save-dev jest
```

Create `math.test.js` next to your source file:

```javascript
// math.test.js
const { add, multiply } = require('./math');

describe('math helpers', () => {
  test('adds two numbers', () => {
    expect(add(2, 3)).toBe(5);
  });

  test('multiplies two numbers', () => {
    expect(multiply(4, 5)).toBe(20);
  });
});
```

Then open `package.json` and update the `test` script:

```json
{
  "scripts": {
    "test": "jest"
  }
}
```

Run it locally to make sure everything passes:

```bash
npm test
```

You should see something like:

```text
 PASS  ./math.test.js
  math helpers
    ✓ adds two numbers (2 ms)
    ✓ multiplies two numbers

Tests:       2 passed, 2 total
```

🎉 Green locally! Now let's make GitHub do this for us.

### A quick note on `.gitignore`

Before committing, keep `node_modules` out of your repo:

```bash
echo "node_modules/" > .gitignore
```

> **Important:** Make sure you commit `package-lock.json`. CI uses it to install the *exact* same dependency versions you have locally, and our caching step depends on it too.

## Step 4: Write Your First Workflow

GitHub Actions looks for workflow files in a very specific place: `.github/workflows/`. Let's create it:

```bash
mkdir -p .github/workflows
```

Now create `.github/workflows/ci.yml` with the following contents:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - name: Check out code
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install dependencies
        run: npm ci

      - name: Run tests
        run: npm test
```

Let's break down what's going on here:

| Section | What it does |
|---|---|
| `name` | The label you'll see in the **Actions** tab |
| `on` | Which events trigger the workflow (pushes and PRs to `main`) |
| `jobs.test` | A single job named `test` |
| `runs-on` | The virtual machine type GitHub spins up for us |
| `steps` | The commands to run, in order |

Why `npm ci` instead of `npm install`? Because `npm ci` installs exactly what's in your lockfile and fails loudly if `package.json` and `package-lock.json` disagree. That's exactly the strictness you want in CI.

## Step 5: Push and Watch It Run

Commit everything and push:

```bash
git add .
git commit -m "Add math helpers, tests, and CI workflow"
git push origin main
```

Now open your repo on GitHub and click the **Actions** tab. You should see your workflow spinning up. Click into it to watch each step stream its logs in real time. After a short wait, you'll (hopefully!) get a green checkmark. ✅

**If it fails**, don't panic. Click the failing step, read the log, and fix it locally. The most common beginner issues are:

- Forgetting to commit `package-lock.json`
- A typo in the YAML indentation (YAML is *very* picky about spaces)
- The `test` script still being the default `echo "Error: no test specified" && exit 1`

## Step 6: Test Against Multiple Node.js Versions

Your users might not all be on the same Node.js version. A **build matrix** lets you run the same job against several versions in parallel. Update the `test` job:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest

    strategy:
      matrix:
        node-version: [18, 20, 22]

    steps:
      - name: Check out code
        uses: actions/checkout@v4

      - name: Set up Node.js ${{ matrix.node-version }}
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}

      - name: Install dependencies
        run: npm ci

      - name: Run tests
        run: npm test
```

Push again, and you'll see three jobs running side by side, one per version. Pretty neat for a handful of extra lines.

> **Note:** Pick versions that match what your project actually supports. Check the [Node.js release schedule](https://nodejs.org/en/about/previous-releases) to see which versions are still maintained.

## Step 7: Speed Things Up with Caching

Every run currently downloads all your packages from scratch. For a tiny project that's fine, but it adds up fast. Luckily, `actions/setup-node` has built-in caching for npm. Just add one line:

```yaml
      - name: Set up Node.js ${{ matrix.node-version }}
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: npm
```

Under the hood, this caches npm's download cache and uses a hash of your `package-lock.json` as the key. When the lockfile changes, the cache is refreshed automatically. When it doesn't, installs get noticeably faster.

To confirm it's working, open a run and expand the **Set up Node.js** step. On the second run, you should see a message indicating the cache was restored.

## Step 8: Add a Status Badge

Time for the fun part: bragging rights. Create a `README.md` in the root of your repo:

```markdown
# hello-ci

![CI](https://github.com/<your-username>/hello-ci/actions/workflows/ci.yml/badge.svg)

A tiny Node.js project with a GitHub Actions CI pipeline.
```

Replace `<your-username>` with your GitHub username. The badge path follows the pattern `actions/workflows/<workflow-file>/badge.svg`, so if you renamed `ci.yml`, update it to match.

> **Shortcut:** On the Actions tab, open your workflow, click the **⋯** menu, and choose **Create status badge**. GitHub will generate the Markdown for you.

Commit and push:

```bash
git add README.md .github/workflows/ci.yml
git commit -m "Add Node.js matrix, npm caching, and CI badge"
git push origin main
```

Refresh your repo page and admire that little green "passing" badge. You earned it.

## The Final Workflow

Here's the complete `ci.yml` for reference:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    strategy:
      matrix:
        node-version: [18, 20, 22]

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: npm

      - run: npm ci
      - run: npm test
```

## Where to Go Next

You've got a solid foundation. Here are some ideas for leveling up:

- [ ] Add a linting step with ESLint (`npm run lint`)
- [ ] Upload test coverage reports as artifacts
- [ ] Require the CI check to pass before merging, using branch protection rules
- [ ] Run the matrix on `windows-latest` and `macos-latest` too
- [ ] Explore the [GitHub Actions documentation](https://docs.github.com/actions) for deployment workflows

## Wrapping Up

Let's recap what we built:

1. A small Node.js project with real tests
2. A GitHub Actions workflow that runs on every push and pull request
3. A matrix that tests several Node.js versions in parallel
4. npm caching to keep builds fast
5. A status badge so everyone can see the build is healthy

CI is one of those things that feels like overhead until the first time it catches a bug before your teammates (or users) do. From now on, every change you push gets checked automatically, and that's a pretty great feeling.

Happy building! 🚀
